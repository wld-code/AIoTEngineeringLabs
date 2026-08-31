"""Lab 5 — Device Twin API.

The local twin service: the one place that knows both what the platform
*wants* (desired state) and what the device has *confirmed* (reported
state). Neither half is the truth on its own — this file's job is making
the gap between them visible, not hiding it.

Endpoints:
  GET  /api/twin/{device}           -> desired + reported + telemetry + sync
  POST /api/twin/{device}/desired   -> request a new reporting interval
  GET  /api/health                  -> liveness for docker compose / curl
  GET  /                            -> the small web UI (static/index.html)

State lives in Redis, latest values only (see docstrings on the two MQTT
handlers below for exactly what each topic updates). No history — that's
Chapter 6's job, not this lab's.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import redis
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

DEVICE_ID = "sim-001"
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

TOPIC_PROCESSED = f"devices/{DEVICE_ID}/telemetry/processed"
TOPIC_DESIRED = f"devices/{DEVICE_ID}/twin/desired"
TOPIC_REPORTED = f"devices/{DEVICE_ID}/twin/reported"

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Device Twin API", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


# --------------------------------------------------------------- MQTT in ---
def _on_processed(_client, _userdata, msg):
    """devices/sim-001/telemetry/processed -> twin:sim-001:telemetry.
    The only thing this handler does is remember the latest processed
    reading — it does not touch desired or reported state."""
    try:
        d = json.loads(msg.payload)
        r.hset(f"twin:{DEVICE_ID}:telemetry", mapping={
            "temperature_c": d["temperature_c"],
            "average_temperature_c": d["average_temperature_c"],
            "alarm": json.dumps(d["alarm"]),
            "timestamp": d["timestamp"],
        })
    except (ValueError, KeyError) as exc:
        print(f"twin-api: bad processed-telemetry payload: {exc}", flush=True)


def _on_reported(_client, _userdata, msg):
    """devices/sim-001/twin/reported -> twin:sim-001:reported. This is the
    device confirming (or rejecting) a command — never written by the POST
    handler itself, only by this subscriber, so "reported" always means
    "the device said so", not "the API assumed so"."""
    try:
        d = json.loads(msg.payload)
        fields = {
            "version": d["version"],
            "reporting_interval_s": d["reporting_interval_s"],
            "status": d["status"],
            "reported_at": d["reported_at"],
        }
        if "reason" in d:
            fields["reason"] = d["reason"]
        r.hset(f"twin:{DEVICE_ID}:reported", mapping=fields)
    except (ValueError, KeyError) as exc:
        print(f"twin-api: bad reported-state payload: {exc}", flush=True)


def _mqtt_thread() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="twin-api")

    def on_connect(c, _userdata, _flags, _rc, _props=None):
        c.subscribe(TOPIC_PROCESSED, qos=0)
        c.subscribe(TOPIC_REPORTED, qos=1)

    def on_message(client, userdata, msg):
        if msg.topic == TOPIC_PROCESSED:
            _on_processed(client, userdata, msg)
        elif msg.topic == TOPIC_REPORTED:
            _on_reported(client, userdata, msg)

    client.on_connect = on_connect
    client.on_message = on_message

    # Same reasoning as device-simulator/simulator.py: depends_on only
    # orders container starts, it doesn't wait for mosquitto to be ready.
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            break
        except OSError as exc:
            print(f"twin-api: mqtt connect failed ({exc}), retrying in 2s", flush=True)
            time.sleep(2)

    app.state.mqtt_client = client
    client.loop_forever()  # reconnects automatically on a later, temporary drop


threading.Thread(target=_mqtt_thread, daemon=True).start()


# -------------------------------------------------------------- helpers ---
def _get_hash(key: str) -> dict:
    h = r.hgetall(key)
    if not h:
        return h
    if "alarm" in h:
        h["alarm"] = json.loads(h["alarm"])
    if "version" in h:
        h["version"] = int(h["version"])
    for k in ("reporting_interval_s", "temperature_c", "average_temperature_c"):
        if k in h:
            h[k] = float(h[k])
    return h


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------- routes ---
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/twin/{device}")
def get_twin(device: str):
    if device != DEVICE_ID:
        raise HTTPException(404, "unknown device")

    desired = _get_hash(f"twin:{device}:desired")
    reported = _get_hash(f"twin:{device}:reported")
    telemetry = _get_hash(f"twin:{device}:telemetry")

    synchronized = bool(
        desired and reported
        and reported.get("status") == "applied"
        and desired.get("version") == reported.get("version")
        and desired.get("reporting_interval_s") == reported.get("reporting_interval_s")
    )

    if desired and reported and desired.get("version") == reported.get("version"):
        command_status = reported.get("status", "pending")
    elif desired:
        command_status = "pending"
    else:
        command_status = None

    staleness_seconds = None
    if telemetry.get("timestamp"):
        staleness_seconds = round(
            (datetime.now(timezone.utc) - _parse_iso(telemetry["timestamp"])).total_seconds(), 1
        )

    return {
        "device_id": device,
        "desired": desired or None,
        "reported": reported or None,
        "telemetry": telemetry or None,
        "command_status": command_status,
        "synchronized": synchronized,
        "staleness_seconds": staleness_seconds,
    }


class DesiredIn(BaseModel):
    # gt=0 is the API's own structural check (a well-formed request). The
    # semantic range (0.5-10 s) is deliberately NOT enforced here — the
    # device is the sole authority on what it will accept, exactly like a
    # real twin. Send 20 and watch it travel all the way to the simulator
    # before coming back "rejected".
    reporting_interval_s: float = Field(..., gt=0, description="Requested reporting interval, in seconds")


@app.post("/api/twin/{device}/desired")
def post_desired(device: str, body: DesiredIn):
    if device != DEVICE_ID:
        raise HTTPException(404, "unknown device")

    current_desired = _get_hash(f"twin:{device}:desired")
    next_version = int(current_desired.get("version", 0)) + 1
    requested_at = iso_now()

    desired_payload = {
        "version": next_version,
        "reporting_interval_s": body.reporting_interval_s,
        "requested_at": requested_at,
    }
    r.hset(f"twin:{device}:desired", mapping=desired_payload)

    client: mqtt.Client = app.state.mqtt_client
    info = client.publish(TOPIC_DESIRED, json.dumps(desired_payload), qos=1)
    info.wait_for_publish(timeout=5)

    # "pending" — the broker has the message. It does NOT mean the device
    # has applied it; that only happens once devices/sim-001/twin/reported
    # arrives and _on_reported() writes it, which GET /api/twin/{device}
    # then reflects as command_status "applied" or "rejected".
    return {"device_id": device, "desired": desired_payload, "status": "pending"}

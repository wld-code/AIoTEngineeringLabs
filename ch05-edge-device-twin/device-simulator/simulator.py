"""Lab 5 — Device Twin: simulated temperature sensor.

Stands in for a physical device. Publishes raw telemetry at
`reporting_interval_s` (starts at 1 s) and applies a new interval only when
the Device Twin API publishes a desired-state command the device accepts.

devices/sim-001/telemetry/raw   <- published here, every reporting_interval_s
devices/sim-001/twin/desired    -> subscribed; a requested reporting interval
devices/sim-001/twin/reported   <- published here, once per desired command,
                                    "applied" or "rejected"

The point of this file is the desired/reported split: a command on
twin/desired is a *request*. Nothing changes until this simulator validates
it and reports back on twin/reported — "published" is not "applied".
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("simulator")

DEVICE_ID = "sim-001"
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TOPIC_RAW = f"devices/{DEVICE_ID}/telemetry/raw"
TOPIC_DESIRED = f"devices/{DEVICE_ID}/twin/desired"
TOPIC_REPORTED = f"devices/{DEVICE_ID}/twin/reported"

MIN_INTERVAL_S = 0.5
MAX_INTERVAL_S = 10.0


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


class Device:
    """Holds the one piece of mutable state a real device would keep in
    flash: the reporting interval it's actually operating at right now."""

    def __init__(self) -> None:
        self.reporting_interval_s = 1.0
        self.last_seen_version = 0
        self.lock = threading.Lock()

    def apply_desired(self, client: mqtt.Client, body: dict) -> None:
        version = body.get("version")
        requested = body.get("reporting_interval_s")
        if not isinstance(version, int) or requested is None:
            log.warning("malformed desired-state message, ignoring: %s", body)
            return

        with self.lock:
            if version <= self.last_seen_version:
                log.info("desired version=%s <= last seen %s, ignoring (stale/duplicate)",
                          version, self.last_seen_version)
                return
            self.last_seen_version = version

        try:
            requested = float(requested)
            valid = MIN_INTERVAL_S <= requested <= MAX_INTERVAL_S
        except (TypeError, ValueError):
            valid = False

        if valid:
            with self.lock:
                self.reporting_interval_s = requested
            ack = {
                "device_id": DEVICE_ID,
                "version": version,
                "reporting_interval_s": requested,
                "status": "applied",
                "reported_at": iso_now(),
            }
            log.info("desired version=%s reporting_interval_s=%s -> applied", version, requested)
        else:
            ack = {
                "device_id": DEVICE_ID,
                "version": version,
                "reporting_interval_s": requested,
                "status": "rejected",
                "reason": f"reporting_interval_s must be between {MIN_INTERVAL_S} and {MAX_INTERVAL_S}",
                "reported_at": iso_now(),
            }
            log.warning("desired version=%s reporting_interval_s=%s -> rejected", version, requested)

        client.publish(TOPIC_REPORTED, json.dumps(ack), qos=1)

    def current_interval(self) -> float:
        with self.lock:
            return self.reporting_interval_s


def make_on_message(device: Device, client: mqtt.Client):
    def on_message(_client, _userdata, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            log.warning("desired-state payload was not valid JSON: %r", msg.payload)
            return
        device.apply_desired(client, body)
    return on_message


def telemetry_loop(client: mqtt.Client, device: Device) -> None:
    while True:
        temperature_c = round(22.0 + random.gauss(0, 0.5), 2)
        payload = {
            "device_id": DEVICE_ID,
            "timestamp": iso_now(),
            "temperature_c": temperature_c,
            "reporting_interval_s": device.current_interval(),
        }
        client.publish(TOPIC_RAW, json.dumps(payload), qos=0)
        log.info("published raw telemetry: %s", payload)
        time.sleep(device.current_interval())


def main() -> None:
    device = Device()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{DEVICE_ID}-sim")

    def on_connect(c, _userdata, _flags, _rc, _props=None):
        c.subscribe(TOPIC_DESIRED, qos=1)
        log.info("connected to broker, subscribed to %s", TOPIC_DESIRED)

    client.on_connect = on_connect
    client.on_message = make_on_message(device, client)

    # docker-compose's depends_on only guarantees container start order, not
    # that mosquitto is accepting connections yet — retry the initial
    # connect instead of crashing on a cold-start race. Once connected,
    # loop_start()'s automatic reconnect (reconnect_on_failure=True by
    # default in paho-mqtt 2.x) covers any later, temporary disconnection.
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            break
        except OSError as exc:
            log.warning("mqtt connect failed (%s), retrying in 2s", exc)
            time.sleep(2)

    client.loop_start()
    log.info("device %s online, reporting_interval_s=%s", DEVICE_ID, device.current_interval())
    telemetry_loop(client, device)


if __name__ == "__main__":
    main()

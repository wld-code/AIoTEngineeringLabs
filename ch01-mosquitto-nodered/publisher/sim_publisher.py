"""Simulated device fleet for Lab 1.

Ten devices across two production lines publish temperature telemetry to a
local Mosquitto broker. Each device drifts slowly around a baseline and
occasionally spikes above 80 C, which Node-RED turns into an alarm.

Two operating modes — the architectural shift from Chapter 1:

  raw       every reading reaches the broker. Centralised telemetry: the
            cloud sees everything and pays to transport, process and store it.

  filtered  the device decides locally. It publishes only readings it
            considers anomalous, plus a periodic summary so the platform
            still knows the device is alive. Distributed intelligence:
            ~99 % less traffic for the same operational visibility.

Select the mode with the PUBLISH_MODE env var or argv[1]:

    python sim_publisher.py                 # raw  (default)
    python sim_publisher.py filtered        # filtered
    PUBLISH_MODE=filtered python sim_publisher.py

Topic shape: factory/<line>/<device>/temperature
Payload:     {"ts": <unix_ms>, "value": <float>, "unit": "C", "kind": <str>}
"""

from __future__ import annotations

import json
import os
import random
import signal
import sys
import time
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "1883"))
PUBLISH_INTERVAL_S = float(os.environ.get("PUBLISH_INTERVAL_S", "0.5"))
SUMMARY_INTERVAL_S = float(os.environ.get("SUMMARY_INTERVAL_S", "10"))
SPIKE_PROBABILITY = 0.05  # 5% of readings spike upward

VALID_MODES = ("raw", "filtered")


def resolve_mode() -> str:
    mode = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PUBLISH_MODE", "raw"))
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        print(f"[sim] unknown mode '{mode}', expected one of {VALID_MODES}", file=sys.stderr)
        sys.exit(2)
    return mode


@dataclass
class Device:
    line: str
    device_id: str
    baseline_c: float
    # filtered-mode local state
    _last_summary_at: float = field(default=0.0)
    _window: list[float] = field(default_factory=list)

    @property
    def topic(self) -> str:
        return f"factory/{self.line}/{self.device_id}/temperature"

    def next_reading(self) -> float:
        drift = random.gauss(0, 0.3)
        spike = random.uniform(15, 25) if random.random() < SPIKE_PROBABILITY else 0
        return round(self.baseline_c + drift + spike, 2)

    def is_anomaly(self, value: float) -> bool:
        # Local decision, on the device, with no cloud involved: anything more
        # than 8 C above baseline is "interesting enough to report".
        return value > self.baseline_c + 8.0

    def emit(self, value: float, mode: str, now: float) -> list[tuple[str, dict]]:
        """Return the list of (topic, payload) the device chooses to publish."""
        ts = int(now * 1000)
        if mode == "raw":
            return [(self.topic, {"ts": ts, "value": value, "unit": "C", "kind": "raw"})]

        # filtered: report anomalies immediately ...
        out: list[tuple[str, dict]] = []
        self._window.append(value)
        if self.is_anomaly(value):
            out.append((self.topic, {"ts": ts, "value": value, "unit": "C", "kind": "anomaly"}))

        # ... plus a heartbeat summary so the platform knows we are alive.
        if now - self._last_summary_at >= SUMMARY_INTERVAL_S and self._window:
            avg = round(sum(self._window) / len(self._window), 2)
            out.append((self.topic, {
                "ts": ts, "value": avg, "unit": "C", "kind": "summary",
                "n": len(self._window),
                "min": round(min(self._window), 2),
                "max": round(max(self._window), 2),
            }))
            self._last_summary_at = now
            self._window.clear()
        return out


def build_fleet() -> list[Device]:
    fleet: list[Device] = []
    for i in range(1, 6):
        fleet.append(Device(line="line-1", device_id=f"dev-{i:02d}", baseline_c=72.0))
    for i in range(1, 6):
        fleet.append(Device(line="line-2", device_id=f"dev-{i:02d}", baseline_c=75.0))
    return fleet


def main() -> int:
    mode = resolve_mode()
    # VERSION2 — paho-mqtt 2.x deprecates VERSION1 outright (it still works,
    # but warns on every run, explicit choice or not). VERSION2 changes the
    # on_connect signature to include connect_flags and a ReasonCode instead
    # of a plain int rc.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sim-publisher")

    def on_connect(client, _userdata, _connect_flags, reason_code, _properties=None):
        if not reason_code.is_failure:
            print(f"[sim] connected to {BROKER_HOST}:{BROKER_PORT}")
        else:
            print(f"[sim] connection failed: {reason_code}", file=sys.stderr)

    client.on_connect = on_connect

    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    except OSError as exc:
        print(f"[sim] cannot reach broker at {BROKER_HOST}:{BROKER_PORT}: {exc}", file=sys.stderr)
        print("[sim] is the docker compose stack up? -> docker compose up -d", file=sys.stderr)
        return 1

    client.loop_start()
    fleet = build_fleet()
    print(
        f"[sim] mode={mode} — publishing from {len(fleet)} devices "
        f"every {PUBLISH_INTERVAL_S}s — Ctrl+C to stop"
    )
    if mode == "filtered":
        print(f"[sim] filtered: anomalies + a summary every {SUMMARY_INTERVAL_S:.0f}s per device")

    stop = False

    def handle_sigint(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sigint)

    sent = 0
    try:
        while not stop:
            now = time.time()
            for d in fleet:
                value = d.next_reading()
                for topic, payload in d.emit(value, mode, now):
                    client.publish(topic, json.dumps(payload), qos=0)
                    sent += 1
            time.sleep(PUBLISH_INTERVAL_S)
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"\n[sim] stopped cleanly — {sent} messages published in {mode} mode.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

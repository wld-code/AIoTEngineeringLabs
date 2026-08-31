#!/usr/bin/env python3
"""Runs inside the client container: capture Test A/B/C/D (or its TLS
variant) with tcpdump on this container's own interface, then run the
matching telemetry_client.py invocation against the broker/server by its
Docker service name.

Because the capture and the client share one network namespace, this
sees exactly the traffic this container sends and receives — no host
loopback interface, no interface-name guessing, no separate capture
permissions to configure. Invoked by run_all_tests.py via
`docker compose exec client python3 run_one_test.py ...`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

TESTS = {
    "A": dict(protocol="mqtt", connection="new", count=1),
    "B": dict(protocol="mqtt", connection="persistent", count=10),
    "C": dict(protocol="http", connection="new", count=1),
    "D": dict(protocol="http", connection="persistent", count=10),
}

PLAIN_PORT = {"mqtt": 1883, "http": 8080}
TLS_PORT = {"mqtt": 8883}  # TLS extension is MQTT-only — see the README
PLAIN_HOST = {"mqtt": "mosquitto", "http": "http_server"}
TLS_HOST = {"mqtt": "mosquitto"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, choices=sorted(TESTS))
    p.add_argument("--tls", action="store_true")
    p.add_argument("--iface", default="eth0")
    p.add_argument("--interval", type=float, default=0.05)
    args = p.parse_args()

    spec = TESTS[args.name]
    protocol = spec["protocol"]
    if args.tls and protocol not in TLS_PORT:
        raise SystemExit(f"the TLS extension only covers MQTT tests (A, B) — got --tls with protocol={protocol}")

    port = TLS_PORT[protocol] if args.tls else PLAIN_PORT[protocol]
    host = TLS_HOST[protocol] if args.tls else PLAIN_HOST[protocol]

    captures = Path("/captures")
    captures.mkdir(exist_ok=True)
    suffix = "_tls" if args.tls else ""
    pcap_path = captures / f"test{args.name}{suffix}.pcap"
    pcap_path.unlink(missing_ok=True)

    tcpdump = subprocess.Popen(
        ["tcpdump", "-i", args.iface, "-w", str(pcap_path), f"tcp port {port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(1.0)  # let tcpdump attach before any traffic starts

    cmd = [
        sys.executable, "/app/telemetry_client.py",
        "--protocol", protocol,
        "--connection", spec["connection"],
        "--count", str(spec["count"]),
        "--host", host,
        "--interval", str(args.interval),
    ]
    if args.tls:
        cmd.append("--tls")

    label = f"Test {args.name}{' + TLS' if args.tls else ''}"
    print(f"=== {label}: {protocol.upper()} / {spec['connection']} / {spec['count']} msg ===", flush=True)
    subprocess.run(cmd, check=True)

    time.sleep(1.0)  # let the last ACK/FIN land in the capture
    tcpdump.terminate()
    try:
        tcpdump.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tcpdump.kill()
        tcpdump.wait()

    size = pcap_path.stat().st_size if pcap_path.exists() else 0
    print(f"[run_one_test] wrote {pcap_path} ({size} bytes)", flush=True)
    print(f"RESULT server_port={port}", flush=True)


if __name__ == "__main__":
    main()

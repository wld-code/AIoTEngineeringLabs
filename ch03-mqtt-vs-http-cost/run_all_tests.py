#!/usr/bin/env python3
"""Lab 3 — run Tests A-D (or, with --tls, the MQTT TLS extension's A/B
pair) end to end: check the stack is up, capture and run each test inside
the `client` container, analyze every resulting pcap, print the
comparison table, and save structured results.

This script is a thin orchestrator. It has no pip dependencies of its
own — every step that needs a real dependency (paho-mqtt, tcpdump, dpkt)
runs inside the `client` container via `docker compose exec`, so the only
thing this needs on the host is Python 3's standard library and a working
`docker compose`.

The step-by-step manual procedure — start a capture, run the client, stop
the capture, apply a Wireshark filter, read Statistics -> Conversations ->
TCP — is what the lab's README also walks through by hand, so a reader
can see each measurement made rather than only a finished table.

Usage:
    python3 run_all_tests.py                # plaintext, Tests A-D
    python3 run_all_tests.py --tls           # TLS extension, Tests A/B only (MQTT)
    python3 run_all_tests.py --figures       # also (re)generate the book's figures, if matplotlib is available
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPTURES = HERE / "captures"
RESULTS = HERE / "results"

TESTS = {
    "A": dict(protocol="MQTT", connection="new", messages=1, port=1883, tls_port=8883),
    "B": dict(protocol="MQTT", connection="persistent", messages=10, port=1883, tls_port=8883),
    "C": dict(protocol="HTTP", connection="new", messages=1, port=8080, tls_port=None),
    "D": dict(protocol="HTTP", connection="persistent", messages=10, port=8080, tls_port=None),
}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def compose_exec(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "exec", "-T", "client", *args]
    return subprocess.run(cmd, cwd=HERE, check=True,
                           stdout=subprocess.PIPE if capture else None,
                           text=True)


def check_services(timeout: float = 30.0) -> None:
    print("Checking services (mosquitto:1883, http_server:8080) ...", flush=True)
    probe = (
        "import socket,sys\n"
        "for host,port in [('mosquitto',1883),('http_server',8080)]:\n"
        "    s=socket.socket(); s.settimeout(2)\n"
        "    try:\n"
        "        s.connect((host,port))\n"
        "    except OSError as e:\n"
        "        print(f'{host}:{port} not reachable: {e}'); sys.exit(1)\n"
        "    finally:\n"
        "        s.close()\n"
        "print('services reachable')\n"
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            compose_exec("python3", "-c", probe)
            return
        except subprocess.CalledProcessError:
            if time.monotonic() > deadline:
                raise SystemExit(
                    "services did not become reachable in time — "
                    "did you run `docker compose up -d --build` first?"
                )
            time.sleep(1.0)


def run_one_test(name: str, tls: bool) -> None:
    args = ["python3", "run_one_test.py", "--name", name]
    if tls:
        args.append("--tls")
    compose_exec(*args)


def analyze_one(name: str, spec: dict, tls: bool) -> dict:
    suffix = "_tls" if tls else ""
    pcap = f"/captures/test{name}{suffix}.pcap"
    port = spec["tls_port"] if tls else spec["port"]
    args = [
        "python3", "analyze_capture.py", pcap,
        "--count", str(spec["messages"]),
        "--server-port", str(port),
        "--json",
    ]
    if tls:
        args.append("--no-breakdown")  # see analyze_capture.py — TLS 1.3 record types don't support this reliably
    proc = compose_exec(*args, capture=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tls", action="store_true", help="run only A and B, against the MQTT TLS listener")
    p.add_argument("--figures", action="store_true", help="also regenerate the book's figures (needs matplotlib)")
    args = p.parse_args()

    CAPTURES.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    check_services()

    names = ["A", "B"] if args.tls else ["A", "B", "C", "D"]

    rows = []
    for name in names:
        spec = TESTS[name]
        label = f"Test {name}{' + TLS' if args.tls else ''}"
        print(f"\n--- {label}: {spec['protocol']} / {spec['connection']} / {spec['messages']} msg ---", flush=True)
        run_one_test(name, args.tls)
        stats = analyze_one(name, spec, args.tls)
        rows.append({"test": name, "protocol": spec["protocol"], "connection": spec["connection"], **stats})

    print("\n" + "=" * 108)
    header = (f"{'Test':<9}{'Protocol':<10}{'Connection':<14}{'Messages':>9}"
              f"{'Total bytes':>13}{'Bytes/msg':>11}{'Efficiency':>12}{'Flows':>8}")
    print(header)
    print("-" * 108)
    for r in rows:
        name = r["test"] + ("+TLS" if args.tls else "")
        print(
            f"{name:<9}{r['protocol']:<10}{r['connection']:<14}{r['message_count']:>9}"
            f"{r['total_network_bytes']:>13}{r['avg_network_bytes_per_message']:>11}"
            f"{r['payload_efficiency_pct']:>11}%{r['tcp_flow_count']:>8}"
        )
    print("=" * 108)

    # Verify the "one TCP connection" claim for the persistent tests.
    for r in rows:
        if r["connection"] == "persistent" and r["tcp_flow_count"] != 1:
            print(
                f"WARNING: Test {r['test']} is persistent but used "
                f"{r['tcp_flow_count']} TCP connections, not 1",
                file=sys.stderr,
            )

    suffix = "_tls" if args.tls else ""
    metadata = {
        "date": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(),
        "docker_version": subprocess.run(["docker", "--version"], capture_output=True, text=True).stdout.strip(),
        "mqtt_version": "3.1.1",
        "http_version": "HTTP/1.1",
        "payload_bytes": 34,
        "tls": args.tls,
    }
    out = {"metadata": metadata, "results": rows}
    (RESULTS / f"results{suffix}.json").write_text(json.dumps(out, indent=2) + "\n")

    with (RESULTS / f"results{suffix}.csv").open("w", newline="") as f:
        fieldnames = ["test", "protocol", "connection", "message_count", "payload_bytes",
                      "total_packets", "total_network_bytes", "avg_network_bytes_per_message",
                      "payload_efficiency_pct", "tcp_flow_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {RESULTS / f'results{suffix}.json'} and {RESULTS / f'results{suffix}.csv'}")

    if args.figures:
        gen = HERE.parent.parent / "scripts" / "generate_ch03_lab_figures.py"
        if gen.exists():
            try:
                run([sys.executable, str(gen)])
            except subprocess.CalledProcessError as e:
                print(f"figure generation failed ({e}) — matplotlib installed?", file=sys.stderr)
        else:
            print(f"figure generator not found at {gen} — skipping", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

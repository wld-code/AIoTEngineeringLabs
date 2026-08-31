#!/usr/bin/env python3
"""Lab 3 — send the same telemetry payload over MQTT or HTTP, in either a
fresh-connection-per-message or a reused-connection pattern, so a packet
capture of each run can be compared byte for byte.

Four tests, matching the lab's procedure:

    A  --protocol mqtt --connection new        --count 1
    B  --protocol mqtt --connection persistent  --count 10
    C  --protocol http --connection new        --count 1
    D  --protocol http --connection persistent  --count 10

The payload is fixed and identical across every test — see PAYLOAD below.
Run with --tls against the optional TLS extension's listeners (8883 / 8443).
"""
from __future__ import annotations

import argparse
import http.client
import ssl
import time

import paho.mqtt.client as mqtt

# Exact payload for every test — do not reformat. Byte-identical across
# protocols and connection modes is what makes the comparison fair.
PAYLOAD = b'{"device":"sensor-01","temp":23.7}'
assert len(PAYLOAD) == 34, f"PAYLOAD changed size: {len(PAYLOAD)} bytes, expected 34"

MQTT_TOPIC = "lab/sensor-01/telemetry"
HTTP_PATH = "/telemetry"


def log(msg: str) -> None:
    print(f"[client] {msg}", flush=True)


# --------------------------------------------------------------------- MQTT

def mqtt_publish_new(host: str, port: int, count: int, tls: bool, interval: float) -> None:
    """One fresh TCP + MQTT CONNECT for every single publish — the cost a
    device pays if it never keeps a session open between readings."""
    for i in range(count):
        client = mqtt.Client(client_id=f"lab3-new-{i}", protocol=mqtt.MQTTv311)
        if tls:
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)  # lab CA is self-signed; see README
        client.connect(host, port, keepalive=60)
        client.loop_start()
        info = client.publish(MQTT_TOPIC, PAYLOAD, qos=0)
        info.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        log(f"published message {i + 1}/{count} (new connection)")
        if i < count - 1:
            time.sleep(interval)


def mqtt_publish_persistent(host: str, port: int, count: int, tls: bool, interval: float) -> None:
    """One TCP + MQTT CONNECT, then every publish reuses the same session —
    the cost once a device keeps its connection open across readings."""
    client = mqtt.Client(client_id="lab3-persistent", protocol=mqtt.MQTTv311)
    if tls:
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    for i in range(count):
        info = client.publish(MQTT_TOPIC, PAYLOAD, qos=0)
        info.wait_for_publish(timeout=5)
        log(f"published message {i + 1}/{count} (persistent connection)")
        if i < count - 1:
            time.sleep(interval)
    client.loop_stop()
    client.disconnect()


# --------------------------------------------------------------------- HTTP

def _http_post(conn: http.client.HTTPConnection, extra_headers: dict[str, str]) -> None:
    headers = {"Content-Type": "application/json", "Content-Length": str(len(PAYLOAD))}
    headers.update(extra_headers)
    conn.request("POST", HTTP_PATH, body=PAYLOAD, headers=headers)
    resp = conn.getresponse()
    resp.read()  # drain the body so the connection stays usable for the next request
    if resp.status != 204:
        raise RuntimeError(f"unexpected HTTP status {resp.status}")


def http_post_new(host: str, port: int, count: int, tls: bool, interval: float) -> None:
    """One fresh TCP (+ TLS handshake if enabled) connection per POST,
    explicitly closed with Connection: close — the naive HTTP pattern."""
    for i in range(count):
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(host, port, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port)
        _http_post(conn, {"Connection": "close"})
        conn.close()
        log(f"posted message {i + 1}/{count} (new connection)")
        if i < count - 1:
            time.sleep(interval)


def http_post_persistent(host: str, port: int, count: int, tls: bool, interval: float) -> None:
    """One TCP connection, kept open across all N POSTs via HTTP/1.1
    keep-alive (the default — no Connection header override needed)."""
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, port, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port)
    for i in range(count):
        _http_post(conn, {})
        log(f"posted message {i + 1}/{count} (persistent connection)")
        if i < count - 1:
            time.sleep(interval)
    conn.close()


# --------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--protocol", choices=["mqtt", "http"], required=True)
    p.add_argument("--connection", choices=["new", "persistent"], required=True)
    p.add_argument("--count", type=int, default=1)
    p.add_argument(
        "--host", default="127.0.0.1",
        help="broker/server host — a Docker service name (mosquitto, "
             "http_server, http_server_tls) when run inside the client "
             "container, or an explicit IPv4 address for a manual host run. "
             "Avoid 'localhost' for a manual run: it can resolve to the "
             "IPv6 ::1 first and split the capture across two address "
             "families for no reason.",
    )
    p.add_argument("--mqtt-port", type=int, default=None)
    p.add_argument("--http-port", type=int, default=None)
    p.add_argument("--tls", action="store_true", help="use the optional TLS listeners (8883 / 8443)")
    p.add_argument("--interval", type=float, default=0.2, help="seconds between messages")
    args = p.parse_args()

    log(f"Payload: {PAYLOAD.decode()}")
    log(f"Application payload size: {len(PAYLOAD)} bytes")

    if args.protocol == "mqtt":
        port = args.mqtt_port or (8883 if args.tls else 1883)
        fn = mqtt_publish_new if args.connection == "new" else mqtt_publish_persistent
        fn(args.host, port, args.count, args.tls, args.interval)
    else:
        port = args.http_port or (8443 if args.tls else 8080)
        fn = http_post_new if args.connection == "new" else http_post_persistent
        fn(args.host, port, args.count, args.tls, args.interval)

    log("done")


if __name__ == "__main__":
    main()

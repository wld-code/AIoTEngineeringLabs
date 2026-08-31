#!/usr/bin/env python3
"""Lab 3 — turn a packet capture into the numbers the comparison table
needs, without requiring Wireshark or tshark. Wireshark's own Statistics ->
Conversations -> TCP panel reports the same "total bytes" figure for anyone
who prefers the GUI; this is the script-friendly equivalent.

Definition used throughout this lab (README, this script, the book text,
every table and figure):

    Total network bytes = the sum of the IP packet lengths observed in
    BOTH directions for the connection(s) under test. Link-layer headers
    (Ethernet, Linux "any"/SLL, BSD loopback) are excluded — this is the
    IPv4 "Total Length" header field, or 40 + the IPv6 "Payload Length"
    field, summed across every captured packet. It is not the raw frame
    size tcpdump reports, and it is not radio airtime or energy — this
    lab does not measure either.

Reads one pcap (or pcapng) written by tcpdump/tshark/Wireshark. Handles
the three link types this lab will realistically see: DLT_NULL (macOS/BSD
loopback), DLT_LINUX_SLL / SLL2 (Linux "any"/loopback), and DLT_EN10MB
(a real interface — the client container's eth0, or an ESP32-S3 over
Wi-Fi for the hardware extension) — over IPv4 or IPv6.

Optional protocol-aware breakdown (TCP establishment / protocol setup /
telemetry exchange / TCP termination): classified at the packet level by
inspecting the first bytes of each payload-carrying TCP segment for a
recognizable MQTT fixed header or HTTP request/response line. This
assumes each MQTT control packet and each HTTP message fits in one TCP
segment — true for this lab's small, sequential, low-rate messages on a
local Docker network, not a general guarantee. If a payload-carrying
packet doesn't match anything recognized, it is reported as
"unclassified" rather than guessed at, and the breakdown is skipped
entirely for TLS captures (see below).

TLS note: TLS 1.3 wires all post-handshake handshake messages with the
same outer record type as encrypted application data, so the outer
record type alone cannot reliably separate "TLS handshake" from
"telemetry" bytes for a TLS 1.3 connection. Rather than infer a boundary
that isn't really there, this script does not attempt the four-row
breakdown for TLS captures — only the three headline metrics (total
bytes, average bytes/message, payload efficiency) are reported for them.

Usage:
    python3 analyze_capture.py captures/testA.pcap --count 1 --server-port 1883
    python3 analyze_capture.py captures/testB.pcap --count 10 --server-port 1883 --json
"""
from __future__ import annotations

import argparse
import json
import sys

import dpkt

PAYLOAD_BYTES = 34  # len(b'{"device":"sensor-01","temp":23.7}') — see client/telemetry_client.py

DLT_NULL = 0
DLT_EN10MB = 1
DLT_LINUX_SLL = 113
DLT_LINUX_SLL2 = 276

# BSD loopback pseudo-header address-family values (host byte order once
# read little-endian on the little-endian platforms this lab targets).
AF_INET_BSD = 2
AF_INET6_BSD = 30

MQTT_TYPE_NAMES = {
    1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 5: "PUBREC",
    6: "PUBREL", 7: "PUBCOMP", 8: "SUBSCRIBE", 9: "SUBACK", 10: "UNSUBSCRIBE",
    11: "UNSUBACK", 12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT",
}
HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"DELETE ", b"HEAD ", b"OPTIONS ")


def _ip_packet(datalink: int, buf: bytes):
    """Return a dpkt IP or IP6 instance for one captured frame, or None if
    it isn't an IP packet this analysis cares about (e.g. an ARP frame)."""
    if datalink == DLT_NULL:
        family = int.from_bytes(buf[:4], sys.byteorder)
        payload = buf[4:]
        if family == AF_INET_BSD:
            return dpkt.ip.IP(payload)
        if family == AF_INET6_BSD:
            return dpkt.ip6.IP6(payload)
        return None
    if datalink == DLT_LINUX_SLL:
        eth_type = int.from_bytes(buf[14:16], "big")
        payload = buf[16:]
    elif datalink == DLT_LINUX_SLL2:
        eth_type = int.from_bytes(buf[0:2], "big")
        payload = buf[20:]
    elif datalink == DLT_EN10MB:
        eth = dpkt.ethernet.Ethernet(buf)
        if isinstance(eth.data, (dpkt.ip.IP, dpkt.ip6.IP6)):
            return eth.data
        return None
    else:
        raise ValueError(f"unsupported link-layer type {datalink} — capture with tcpdump/tshark, not a raw dump")

    if eth_type == 0x0800:
        return dpkt.ip.IP(payload)
    if eth_type == 0x86DD:
        return dpkt.ip6.IP6(payload)
    return None


def _ip_total_len(ip) -> int:
    """The IP packet's own length, excluding any link-layer framing —
    the definition this lab's 'total network bytes' is built on."""
    if isinstance(ip, dpkt.ip6.IP6):
        return 40 + ip.plen  # fixed IPv6 header + payload (TCP header+data, extension headers if any)
    return ip.len  # IPv4 Total Length header field


def _classify_app_payload(payload: bytes) -> str | None:
    """Classify one payload-carrying TCP segment by its leading marker.
    Returns one of 'mqtt_setup', 'mqtt_exchange', 'mqtt_teardown',
    'http_exchange', or None if the segment carries no recognizable
    marker of its own (see the caller: an unmarked segment is treated as
    a continuation of whatever the previous segment *in the same
    direction* was classified as — e.g. an HTTP request's JSON body,
    which Python's http.client sends as its own TCP segment separate
    from the header block that identifies it as a POST).

    Only the MQTT control packet types this lab's client actually sends
    (CONNECT, CONNACK, PUBLISH, DISCONNECT) are recognized by type byte;
    anything else is left unmarked rather than guessed at."""
    if not payload:
        return None
    for method in HTTP_METHODS:
        if payload.startswith(method):
            return "http_exchange"
    if payload.startswith(b"HTTP/1."):
        return "http_exchange"
    mqtt_type = payload[0] >> 4
    if mqtt_type in (1, 2):        # CONNECT, CONNACK
        return "mqtt_setup"
    if mqtt_type == 14:            # DISCONNECT
        return "mqtt_teardown"
    if mqtt_type == 3:             # PUBLISH
        return "mqtt_exchange"
    return None


def analyze(pcap_path: str, message_count: int, server_port: int | None = None,
            breakdown: bool = True) -> dict:
    packets = []
    with open(pcap_path, "rb") as f:
        reader = dpkt.pcap.Reader(f)
        datalink = reader.datalink()
        for ts, buf in reader:
            try:
                ip = _ip_packet(datalink, buf)
            except (dpkt.dpkt.UnpackError, ValueError):
                continue
            if ip is None or not isinstance(ip.data, dpkt.tcp.TCP):
                continue
            tcp = ip.data
            packets.append({
                "ts": ts,
                "ip_len": _ip_total_len(ip),
                "flags": tcp.flags,
                "payload": bytes(tcp.data),
                "src_port": tcp.sport,
                "dst_port": tcp.dport,
            })

    if not packets:
        raise SystemExit(f"{pcap_path}: no TCP/IP packets found — wrong filter, or capture is empty")

    packets.sort(key=lambda p: p["ts"])
    total_packets = len(packets)
    total_bytes = sum(p["ip_len"] for p in packets)

    # --- distinct TCP connections (flows) actually used ---------------------
    if server_port is None:
        # Infer it: the port value common to every packet, either as src or dst.
        candidates = {p["src_port"] for p in packets} & {p["dst_port"] for p in packets}
        if len(candidates) != 1:
            raise SystemExit(
                f"{pcap_path}: cannot infer server port automatically "
                f"(candidates={candidates}) — pass --server-port explicitly"
            )
        server_port = candidates.pop()

    def client_port(p: dict) -> int:
        return p["dst_port"] if p["src_port"] == server_port else p["src_port"]

    flow_ids = sorted({client_port(p) for p in packets})
    tcp_flow_count = len(flow_ids)

    useful_payload = PAYLOAD_BYTES * message_count
    efficiency = 100.0 * useful_payload / total_bytes
    avg_bytes_per_message = total_bytes / message_count if message_count else float(total_bytes)

    result = {
        "file": pcap_path,
        "message_count": message_count,
        "payload_bytes": PAYLOAD_BYTES,
        "total_packets": total_packets,
        "total_network_bytes": total_bytes,
        "avg_network_bytes_per_message": round(avg_bytes_per_message, 1),
        "payload_efficiency_pct": round(efficiency, 2),
        "tcp_flow_count": tcp_flow_count,
    }

    if not breakdown:
        return result

    # --- protocol-aware breakdown, per flow ---------------------------------
    establishment_bytes = 0
    termination_bytes = 0
    setup_bytes = 0
    exchange_bytes = 0
    unclassified_bytes = 0
    unclassified_seen = 0

    for flow in flow_ids:
        flow_packets = [p for p in packets if client_port(p) == flow]
        n = len(flow_packets)
        # Handshake: the leading SYN, SYN+ACK, and first pure ACK (no payload).
        i = 0
        while i < n and i < 3:
            p = flow_packets[i]
            is_syn = bool(p["flags"] & dpkt.tcp.TH_SYN)
            is_pure_ack = len(p["payload"]) == 0 and not (p["flags"] & (dpkt.tcp.TH_FIN | dpkt.tcp.TH_RST))
            if is_syn or is_pure_ack:
                establishment_bytes += p["ip_len"]
                i += 1
            else:
                break
        # Teardown: the trailing FIN/RST run and their pure ACKs.
        j = n - 1
        while j >= i:
            p = flow_packets[j]
            is_fin_rst = bool(p["flags"] & (dpkt.tcp.TH_FIN | dpkt.tcp.TH_RST))
            is_pure_ack = len(p["payload"]) == 0 and not is_fin_rst
            if is_fin_rst or is_pure_ack:
                termination_bytes += p["ip_len"]
                j -= 1
            else:
                break
        # Everything in between: classify payload-carrying segments; pure
        # ACKs in the middle of a persistent exchange carry no useful
        # protocol signal, fold them into the exchange they're servicing.
        #
        # A segment with no marker of its own (e.g. an HTTP request's JSON
        # body, sent as its own TCP segment after the header block) is
        # treated as a continuation of the last classified segment *in the
        # same direction* — tracked separately per direction so a request
        # continuation is never mistaken for a response continuation.
        last_cls = {"c2s": None, "s2c": None}
        for k in range(i, j + 1):
            p = flow_packets[k]
            direction = "c2s" if p["dst_port"] == server_port else "s2c"
            if not p["payload"]:
                exchange_bytes += p["ip_len"]
                continue
            cls = _classify_app_payload(p["payload"])
            if cls is None:
                cls = last_cls[direction]  # continuation segment
                if cls is None:
                    unclassified_bytes += p["ip_len"]
                    unclassified_seen += 1
                    continue
            else:
                last_cls[direction] = cls
            if cls == "mqtt_setup":
                setup_bytes += p["ip_len"]
            elif cls == "mqtt_teardown":
                termination_bytes += p["ip_len"]
            else:  # mqtt_exchange, http_exchange
                exchange_bytes += p["ip_len"]

    result["breakdown"] = {
        "tcp_establishment": establishment_bytes,
        "protocol_setup": setup_bytes,
        "telemetry_exchange": exchange_bytes,
        "tcp_termination": termination_bytes,
        "unclassified": unclassified_bytes,
    }
    if unclassified_seen:
        print(
            f"WARNING: {pcap_path}: {unclassified_seen} payload-carrying packet(s) "
            f"could not be classified ({unclassified_bytes} bytes) — see 'unclassified' "
            f"in the breakdown rather than a guess",
            file=sys.stderr,
        )

    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pcap")
    p.add_argument("--count", type=int, default=1, help="telemetry messages sent during this capture")
    p.add_argument("--server-port", type=int, default=None,
                    help="the fixed server-side port for this test (1883/8080/8883/8443); "
                         "inferred automatically if omitted")
    p.add_argument("--no-breakdown", action="store_true", help="skip the protocol-aware breakdown (used for TLS captures)")
    p.add_argument("--json", action="store_true", help="print one JSON object instead of a text listing")
    args = p.parse_args()

    stats = analyze(args.pcap, args.count, args.server_port, breakdown=not args.no_breakdown)

    if args.json:
        print(json.dumps(stats))
        return

    for k, v in stats.items():
        if k == "breakdown":
            print("breakdown:")
            for bk, bv in v.items():
                print(f"  {bk:>20}: {bv}")
        else:
            print(f"{k:>28}: {v}")


if __name__ == "__main__":
    main()

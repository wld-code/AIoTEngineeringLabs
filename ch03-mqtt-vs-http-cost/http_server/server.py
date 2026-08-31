#!/usr/bin/env python3
"""Minimal telemetry HTTP endpoint for Lab 3's protocol-cost comparison.

Deliberately built on the standard library only (BaseHTTPRequestHandler),
not Flask/FastAPI/etc. A framework adds its own request-routing and
middleware bytes to every response; this lab measures HTTP itself against
MQTT, so the server should add as little of its own overhead as possible.

Accepts POST /telemetry with a JSON body and replies 204 No Content (the
smallest correct response — no body to send back). HTTP/1.1 keep-alive is
on by default (protocol_version = "HTTP/1.1"); a client that sends
"Connection: close" gets the connection closed after the response, which
is exactly the lever Test C vs Test D turns on and off.

The response is deliberately minimal and deterministic: no Date header,
no Server banner, no request-ID. BaseHTTPRequestHandler.send_response()
normally adds Date and Server automatically — do_POST() below calls
send_response_only() instead and sets nothing but Content-Length, so the
byte count on the wire depends only on the protocol and the fixed test
payload, not on this being Python's stdlib server versus any other
implementation.

TLS is optional: set TLS_CERTFILE / TLS_KEYFILE to serve HTTPS instead of
plain HTTP on the same port. Used only by the lab's optional TLS extension.
"""
from __future__ import annotations

import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TelemetryHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # enables keep-alive

    def do_POST(self) -> None:
        if self.path != "/telemetry":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        # Body is read (and discarded) so the connection stays in sync for
        # the next request on a keep-alive socket — an unread body would
        # desynchronize subsequent requests on the same TCP stream.
        self.rfile.read(length)

        # send_response_only(), not send_response(): the latter also injects
        # a Date and a Server header, which would make the measured byte
        # count depend on this particular server implementation rather than
        # on HTTP/1.1 itself.
        self.send_response_only(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quieter container logs
        print(f"[http_server] {self.address_string()} - {fmt % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), TelemetryHandler)

    certfile = os.environ.get("TLS_CERTFILE")
    keyfile = os.environ.get("TLS_KEYFILE")
    if certfile and keyfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print(f"[http_server] HTTPS on :{port} (cert={certfile})")
    else:
        print(f"[http_server] HTTP on :{port}")

    server.serve_forever()


if __name__ == "__main__":
    main()

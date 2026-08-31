#!/usr/bin/env bash
# Optional TLS extension — one CA, one server certificate for Mosquitto's
# TLS listener (8883). Server-auth-only TLS (no client certificates) is
# enough to measure handshake overhead; a full mutual-TLS PKI with device
# certificates and revocation is a separate, deeper lab, not this one's.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 \
  -subj "/CN=Lab 3 TLS extension CA/O=AIoT Book/C=FR" -out ca.crt

openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=mosquitto" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 365 -sha256 \
  -extfile <(printf "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1") \
  -out server.crt
rm -f server.csr ca.srl

chmod 644 server.key   # bind-mounted into the Mosquitto container, read by its own "mosquitto" user
                        # whose UID does not match the host UID. 600 works on Docker Desktop for Mac
                        # but is invisible to that container on native Linux Docker. 644 is readable
                        # across both, an acceptable trade-off for a lab-generated, disposable key.

ls -1 *.crt *.key
echo
echo "Done. Bring the TLS stack up with:"
echo "  docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build"

#!/usr/bin/env bash
# Step 5 (optional) — build a certificate our PKI never issued, for the
# "invalid certificate rejection" demo.
#
# This is deliberately a throwaway, one-off CA — no index.txt, no serial
# tracking, nothing shared with root-ca/ or intermediate-ca/. It exists to
# answer one question on the bench: does the broker actually check the
# issuer, or does it just check "is this a well-formed cert"? A cert with
# the *same* CN as a real device (device-01) but signed by a CA the broker
# was never told to trust makes the point cleanly — identity alone proves
# nothing without a chain back to a trusted root.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

mkdir -p rogue
openssl genrsa -out rogue/rogue-ca.key.pem 2048
openssl req -x509 -new -nodes -key rogue/rogue-ca.key.pem -sha256 -days 3650 \
  -subj "/O=Not Our Fleet/CN=Rogue CA" -out rogue/rogue-ca.cert.pem

openssl genrsa -out rogue/device-01.key.pem 2048
openssl req -new -key rogue/device-01.key.pem \
  -subj "/O=AIoT Lab/CN=device-01" -out rogue/device-01.csr.pem
openssl x509 -req -in rogue/device-01.csr.pem \
  -CA rogue/rogue-ca.cert.pem -CAkey rogue/rogue-ca.key.pem -CAcreateserial \
  -days 825 -sha256 -out rogue/device-01.cert.pem
rm -f rogue/device-01.csr.pem rogue/rogue-ca.srl

echo
echo "Rogue cert built: rogue/device-01.cert.pem"
echo "Same CN as the real device-01, signed by a CA the broker does not trust."

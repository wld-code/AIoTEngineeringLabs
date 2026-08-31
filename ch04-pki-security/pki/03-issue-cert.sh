#!/usr/bin/env bash
# Step 3 — issue a leaf certificate, signed by the Intermediate CA.
#
# Usage:
#   ./03-issue-cert.sh <name> client                          # device identity
#   ./03-issue-cert.sh <name> server "DNS:host,IP:127.0.0.1"  # broker identity
#
# "client" and "server" pick the X.509 extendedKeyUsage — the field a TLS
# stack checks to refuse a device cert offered as a server cert, or the
# reverse. Getting this wrong is a common real-world misissuance bug.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

NAME="${1:?usage: $0 <name> <client|server> [SAN]}"
ROLE="${2:?usage: $0 <name> <client|server> [SAN]}"
SAN="${3:-}"

export INT_CA_DIR="$DIR/intermediate-ca"
if [[ ! -f "$INT_CA_DIR/certs/intermediate.cert.pem" ]]; then
  echo "No intermediate CA found — run ./02-init-intermediate-ca.sh first." >&2
  exit 1
fi

# The key file is chmod 400 once issued (see below), so re-running this
# script for a name that already has a cert fails on "genrsa: Permission
# denied" — technically correct but not an obviously actionable message.
# Fail early with a clear one instead: re-issuing on purpose (e.g. after a
# real rotation) means removing the old files first, not overwriting them
# silently.
if [[ -f "${NAME}.key.pem" || -f "${NAME}.cert.pem" ]]; then
  echo "${NAME}.key.pem or ${NAME}.cert.pem already exists in $DIR." >&2
  echo "Remove both first if you mean to re-issue: rm -f ${NAME}.key.pem ${NAME}.cert.pem" >&2
  exit 1
fi

case "$ROLE" in
  client) EKU="clientAuth" ;;
  server) EKU="serverAuth" ;;
  *) echo "role must be 'client' or 'server', got: $ROLE" >&2; exit 1 ;;
esac

openssl genrsa -out "${NAME}.key.pem" 2048
chmod 400 "${NAME}.key.pem"

openssl req -config intermediate-ca.cnf -new -sha256 \
  -key "${NAME}.key.pem" -subj "/O=AIoT Lab/CN=${NAME}" \
  -out "${NAME}.csr.pem"

# keyEncipherment is deliberately left out: it covers the RSA key-transport
# key exchange TLS 1.2 and earlier use, which this lab's broker never
# negotiates (mosquitto.conf pins tls_version tlsv1.3). TLS 1.3's
# certificate-based authentication, client and server alike, only ever
# needs the key for signing.
EXT="basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=${EKU}"
if [[ -n "$SAN" ]]; then
  EXT="${EXT}
subjectAltName=${SAN}"
fi

# 825 days (~2.25 years) — issued by the intermediate, so a compromised leaf
# key is a routine reissue against the same intermediate, not an
# every-device-in-the-fleet event.
openssl ca -batch -config intermediate-ca.cnf -days 825 -notext -md sha256 \
  -in "${NAME}.csr.pem" -out "${NAME}.cert.pem" \
  -extfile <(printf '%s\n' "$EXT")

rm -f "${NAME}.csr.pem"

echo
echo "Issued ${ROLE} cert for '${NAME}':"
openssl x509 -noout -subject -issuer -dates -in "${NAME}.cert.pem"
echo "  key:  $DIR/${NAME}.key.pem"
echo "  cert: $DIR/${NAME}.cert.pem"

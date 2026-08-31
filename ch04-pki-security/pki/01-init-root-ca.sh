#!/usr/bin/env bash
# Step 1 — create the Root CA.
#
# In production this key is generated once, on an air-gapped machine, and
# never touches a network again — it lives in an HSM or a safe. Here it
# lives in root-ca/private/, because this is a lab, not a fleet. Treat the
# distinction as the whole point: everything past this script pretends the
# root is offline, and only ever asks it to sign one thing (the
# intermediate, in step 2).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export ROOT_CA_DIR="$DIR/root-ca"

if [[ -f "$ROOT_CA_DIR/certs/ca.cert.pem" ]]; then
  echo "Root CA already exists at $ROOT_CA_DIR — delete it first to regenerate."
  exit 0
fi

mkdir -p "$ROOT_CA_DIR"/{certs,crl,newcerts,private}
chmod 700 "$ROOT_CA_DIR/private"
touch "$ROOT_CA_DIR/index.txt"
echo 1000 > "$ROOT_CA_DIR/serial"
echo 1000 > "$ROOT_CA_DIR/crlnumber"

# 4096-bit RSA — this key signs one thing in its entire life (the
# intermediate cert), so the extra bits cost nothing operationally.
openssl genrsa -out "$ROOT_CA_DIR/private/ca.key.pem" 4096
chmod 400 "$ROOT_CA_DIR/private/ca.key.pem"

# Self-signed, 20-year validity (7300 days) — a root has no issuer to renew
# it against, so its validity window has to outlive the product line.
openssl req -config root-ca.cnf -x509 -new -nodes -sha256 -days 7300 \
  -key "$ROOT_CA_DIR/private/ca.key.pem" \
  -extensions v3_root_ca \
  -subj "/O=AIoT Lab/CN=AIoT Lab Root CA" \
  -out "$ROOT_CA_DIR/certs/ca.cert.pem"
chmod 444 "$ROOT_CA_DIR/certs/ca.cert.pem"

echo
echo "Root CA created: $ROOT_CA_DIR/certs/ca.cert.pem"
openssl x509 -noout -subject -issuer -dates -in "$ROOT_CA_DIR/certs/ca.cert.pem"

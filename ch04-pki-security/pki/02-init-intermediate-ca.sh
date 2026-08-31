#!/usr/bin/env bash
# Step 2 — create the Intermediate CA and have the Root CA sign it.
#
# This is the only certificate the root ever signs in this lab. Everything
# downstream — device certs, the broker's server cert, the CRL — is signed
# by the intermediate. That split is the entire point of a two-level PKI:
# compromise or rotate the intermediate without ever touching the root.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export ROOT_CA_DIR="$DIR/root-ca"
export INT_CA_DIR="$DIR/intermediate-ca"

if [[ ! -f "$ROOT_CA_DIR/certs/ca.cert.pem" ]]; then
  echo "No root CA found — run ./01-init-root-ca.sh first." >&2
  exit 1
fi

if [[ -f "$INT_CA_DIR/certs/intermediate.cert.pem" ]]; then
  echo "Intermediate CA already exists at $INT_CA_DIR — delete it first to regenerate."
  exit 0
fi

mkdir -p "$INT_CA_DIR"/{certs,crl,csr,newcerts,private}
chmod 700 "$INT_CA_DIR/private"
touch "$INT_CA_DIR/index.txt"
echo 1000 > "$INT_CA_DIR/serial"
echo 1000 > "$INT_CA_DIR/crlnumber"

openssl genrsa -out "$INT_CA_DIR/private/intermediate.key.pem" 3072
chmod 400 "$INT_CA_DIR/private/intermediate.key.pem"

openssl req -config intermediate-ca.cnf -new -sha256 \
  -key "$INT_CA_DIR/private/intermediate.key.pem" \
  -subj "/O=AIoT Lab/CN=AIoT Lab Intermediate CA" \
  -out "$INT_CA_DIR/csr/intermediate.csr.pem"

# The root signs the intermediate's CSR — the one operation the root ever
# performs in this lab. 5-year validity (1825 days): shorter than the root,
# long enough that operators aren't re-signing it every quarter.
openssl ca -batch -config root-ca.cnf -extensions v3_intermediate_ca \
  -days 1825 -notext -md sha256 \
  -in "$INT_CA_DIR/csr/intermediate.csr.pem" \
  -out "$INT_CA_DIR/certs/intermediate.cert.pem"
chmod 444 "$INT_CA_DIR/certs/intermediate.cert.pem"

# openssl ca -revoke (used later, in 04-revoke-cert.sh) reads the *issuing*
# CA's own database — it needs the intermediate's index.txt/serial to
# already point at itself, not at the root's records.
cat "$INT_CA_DIR/certs/intermediate.cert.pem" "$ROOT_CA_DIR/certs/ca.cert.pem" \
  > "$INT_CA_DIR/certs/ca-chain.cert.pem"

echo
echo "Intermediate CA created and signed by the root:"
openssl x509 -noout -subject -issuer -dates -in "$INT_CA_DIR/certs/intermediate.cert.pem"
echo
echo "Chain file for TLS: $INT_CA_DIR/certs/ca-chain.cert.pem (intermediate + root)"
openssl verify -CAfile "$ROOT_CA_DIR/certs/ca.cert.pem" "$INT_CA_DIR/certs/intermediate.cert.pem"

# Mosquitto's crlfile directive expects a valid CRL to be present at every
# startup, not just after the first revocation — an intermediate CA
# publishes an (initially empty) CRL the moment it exists, same as
# production. 04-revoke-cert.sh republishes this file every time a
# certificate is revoked.
openssl ca -config intermediate-ca.cnf -gencrl -out "$INT_CA_DIR/crl/intermediate.crl.pem"
echo "Initial (empty) CRL published: $INT_CA_DIR/crl/intermediate.crl.pem"

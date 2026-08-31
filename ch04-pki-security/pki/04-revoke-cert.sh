#!/usr/bin/env bash
# Step 4 — revoke a device certificate and republish the CRL.
#
# Usage: ./04-revoke-cert.sh <name>
#
# This is the PKI answer to "the device was stolen" or "the key leaked":
# the certificate stays cryptographically valid (signature, dates all still
# check out) but the intermediate CA now publishes its serial number on a
# list every TLS client and server is expected to check.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

NAME="${1:?usage: $0 <name>}"
export INT_CA_DIR="$DIR/intermediate-ca"

if [[ ! -f "${NAME}.cert.pem" ]]; then
  echo "No cert named ${NAME}.cert.pem in $DIR — did you run 03-issue-cert.sh for it?" >&2
  exit 1
fi

echo "Revoking ${NAME}.cert.pem..."
openssl ca -config intermediate-ca.cnf -revoke "${NAME}.cert.pem" \
  -crl_reason keyCompromise

echo "Regenerating the CRL..."
openssl ca -config intermediate-ca.cnf -gencrl \
  -out "$INT_CA_DIR/crl/intermediate.crl.pem"

cp "$INT_CA_DIR/crl/intermediate.crl.pem" "../certs/intermediate.crl.pem"

echo
echo "CRL updated: $INT_CA_DIR/crl/intermediate.crl.pem (synced to ../certs/)"
openssl crl -in "$INT_CA_DIR/crl/intermediate.crl.pem" -noout -text \
  | grep -A2 "Revoked Certificates"
echo
echo "Restart Mosquitto so it re-reads the CRL file — it is only loaded at startup:"
echo "  docker compose restart mosquitto"

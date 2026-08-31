#!/usr/bin/env bash
# Step 6 — copy the files Mosquitto actually needs into ../certs/, the
# directory docker-compose.yml bind-mounts into the container.
#
# Mosquitto never reads pki/ directly: that directory also holds CA private
# keys, which have no business inside a container image or bind mount.
# ../certs/ is the deliberately narrow subset — chain, broker identity, CRL.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

OUT="../certs"
mkdir -p "$OUT"

cp intermediate-ca/certs/ca-chain.cert.pem "$OUT/"
cp broker.key.pem "$OUT/"
cp intermediate-ca/crl/intermediate.crl.pem "$OUT/"

# TLS servers are expected to present their own leaf PLUS every
# intermediate up to (but not including) the root — that's what lets a
# client with only the root in its trust store build the path itself. A
# client would otherwise have to already possess the intermediate to
# validate the broker, which defeats the point of shipping ca-chain as the
# trust anchor. broker.cert.pem alone is not enough here.
cat broker.cert.pem intermediate-ca/certs/intermediate.cert.pem > "$OUT/broker-fullchain.cert.pem"

# broker.key.pem is bind-mounted into the Mosquitto container and read by
# that container's own "mosquitto" user, whose UID does not match your host
# user's UID on native Linux Docker — a 400 file owned by your host UID is
# invisible to it. 644 is an acceptable trade-off for a lab-generated,
# disposable, non-production key.
chmod 644 "$OUT/broker.key.pem"

echo "Synced to $OUT:"
ls -1 "$OUT"

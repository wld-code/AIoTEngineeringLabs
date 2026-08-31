#!/usr/bin/env bash
# Smoke test — Lab 4: two-level PKI, Mosquitto mTLS, per-device ACL,
# revocation via CRL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."
smoke_validate_compose

PKI="$SMOKE_LAB_DIR/pki"
for f in root-ca.cnf intermediate-ca.cnf 01-init-root-ca.sh 02-init-intermediate-ca.sh \
         03-issue-cert.sh 04-revoke-cert.sh 05-issue-rogue-cert.sh 06-sync-broker-certs.sh; do
    [[ -f "$PKI/$f" ]] || smoke_fail "missing pki/$f"
done
smoke_log "OK — pki/ scripts and configs present"

if smoke_full_mode; then
    if ! command -v openssl >/dev/null 2>&1; then
        smoke_skip "openssl not on PATH — skipping full PKI + broker run"
        exit 0
    fi

    chmod +x "$PKI"/*.sh
    (cd "$PKI" && ./01-init-root-ca.sh >/dev/null)
    (cd "$PKI" && ./02-init-intermediate-ca.sh >/dev/null)
    (cd "$PKI" && ./03-issue-cert.sh device-01 client >/dev/null)
    (cd "$PKI" && ./03-issue-cert.sh device-02 client >/dev/null)
    (cd "$PKI" && ./03-issue-cert.sh broker server "DNS:mosquitto.local,DNS:localhost,IP:127.0.0.1" >/dev/null)
    (cd "$PKI" && ./06-sync-broker-certs.sh >/dev/null)
    smoke_log "OK — root CA, intermediate CA, device-01/02 and broker certs issued"

    smoke_compose_up
    trap smoke_compose_down EXIT
    wait_for_tcp localhost 8883 60
    sleep 1   # TCP accept queue can open fractionally before the TLS context is armed
    smoke_log "OK — Mosquitto listening on 8883 (mTLS + ACL + CRL)"

    # ROOT is the client-side trust anchor for every live TLS connection
    # below: the broker always presents its own certificate together with
    # the Intermediate CA certificate (broker-fullchain.cert.pem), so a
    # client that already trusts the root can build the full path itself
    # without being handed the intermediate separately. CHAIN (intermediate
    # + root) is kept only for the one step that is not a live connection —
    # the local `openssl verify -crl_check` call near the end, which has no
    # peer to hand it an intermediate certificate at all.
    ROOT="$PKI/root-ca/certs/ca.cert.pem"
    CHAIN="$PKI/intermediate-ca/certs/ca-chain.cert.pem"

    # --- Part 5: verify a valid mTLS connection -----------------------------

    smoke_log "checking mTLS accepts device-01's certificate (trusted, not yet revoked)"
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" \
        -cert "$PKI/device-01.cert.pem" -key "$PKI/device-01.key.pem" \
        </dev/null 2>&1 | grep -q "Verify return code: 0 (ok)" \
        && smoke_log "OK — TLS 1.3 handshake succeeds, client trusts only the root" \
        || smoke_fail "TLS handshake with a trusted device certificate failed"

    # --- Part 6: break authentication ---------------------------------------

    smoke_log "checking mTLS rejects a connection with no client cert"
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" </dev/null >/dev/null 2>&1 || true
    rejected=0
    for _ in 1 2 3 4 5; do
        if docker compose -f "$SMOKE_LAB_DIR/docker-compose.yml" logs mosquitto 2>/dev/null \
            | grep -q "peer did not return a certificate"; then
            rejected=1
            break
        fi
        sleep 1
    done
    (( rejected == 1 )) \
        && smoke_log "OK — connection without a client cert was rejected" \
        || smoke_fail "connection without a client cert was NOT rejected"

    smoke_log "checking a cert from an untrusted (rogue) CA is rejected"
    (cd "$PKI" && ./05-issue-rogue-cert.sh >/dev/null)
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" \
        -cert "$PKI/rogue/device-01.cert.pem" -key "$PKI/rogue/device-01.key.pem" \
        </dev/null >/dev/null 2>&1 || true
    sleep 1
    docker compose -f "$SMOKE_LAB_DIR/docker-compose.yml" logs mosquitto 2>/dev/null \
        | tail -5 | grep -q "certificate verify failed" \
        && smoke_log "OK — rogue-CA cert (same CN, untrusted issuer) rejected" \
        || smoke_fail "rogue-CA cert was NOT rejected"

    # --- Part 7: verify server identity -------------------------------------

    smoke_log "checking hostname verification accepts a name in the broker cert's SAN"
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" -verify_hostname localhost \
        -cert "$PKI/device-01.cert.pem" -key "$PKI/device-01.key.pem" \
        </dev/null 2>&1 | grep -q "Verify return code: 0 (ok)" \
        && smoke_log "OK — 'localhost' matches the broker certificate's SAN" \
        || smoke_fail "hostname verification failed for a name that IS in the broker cert's SAN"

    smoke_log "checking hostname verification rejects a name NOT in the broker cert's SAN"
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" -verify_hostname wrong-broker.local \
        -cert "$PKI/device-01.cert.pem" -key "$PKI/device-01.key.pem" \
        </dev/null 2>&1 | grep -q "Verify return code: 62 (hostname mismatch)" \
        && smoke_log "OK — 'wrong-broker.local' rejected with a hostname mismatch, same trusted chain" \
        || smoke_fail "hostname verification did NOT reject an endpoint name outside the broker cert's SAN"

    # --- Part 8: break authorization -----------------------------------------

    if command -v mosquitto_pub >/dev/null 2>&1 && command -v mosquitto_sub >/dev/null 2>&1; then
        smoke_log "checking device-01 can publish/subscribe on its own telemetry topic"
        OUT1="$(mktemp)"
        timeout 6 mosquitto_sub -h localhost -p 8883 --cafile "$ROOT" \
            --cert "$PKI/device-01.cert.pem" --key "$PKI/device-01.key.pem" \
            -t 'devices/device-01/telemetry/#' -C 1 >"$OUT1" 2>&1 &
        SUB1=$!
        sleep 1
        mosquitto_pub -h localhost -p 8883 --cafile "$ROOT" \
            --cert "$PKI/device-01.cert.pem" --key "$PKI/device-01.key.pem" \
            -t 'devices/device-01/telemetry/reading' -m '{"t":24.1}' >/dev/null 2>&1 || true
        wait "$SUB1" 2>/dev/null || true
        grep -q '{"t":24.1}' "$OUT1" \
            && smoke_log "OK — device-01 published and received its own telemetry" \
            || smoke_fail "device-01 could not publish/subscribe on its own telemetry topic (ACL misconfigured)"
        rm -f "$OUT1"

        smoke_log "checking device-01 is denied on device-02's telemetry topic"
        OUT2="$(mktemp)"
        timeout 6 mosquitto_sub -h localhost -p 8883 --cafile "$ROOT" \
            --cert "$PKI/device-02.cert.pem" --key "$PKI/device-02.key.pem" \
            -t 'devices/device-02/telemetry/#' -C 1 >"$OUT2" 2>&1 &
        SUB2=$!
        sleep 1
        mosquitto_pub -h localhost -p 8883 --cafile "$ROOT" \
            --cert "$PKI/device-01.cert.pem" --key "$PKI/device-01.key.pem" \
            -t 'devices/device-02/telemetry/reading' -m '{"t":99.9}' >/dev/null 2>&1 || true
        wait "$SUB2" 2>/dev/null || true
        if grep -q '{"t":99.9}' "$OUT2"; then
            smoke_fail "device-01 was able to publish onto device-02's topic — ACL not enforced"
        else
            smoke_log "OK — device-01 denied publish access to device-02's telemetry topic"
        fi
        rm -f "$OUT2"
    else
        smoke_log "mosquitto_pub/mosquitto_sub not on PATH — skipping ACL authorization checks"
    fi

    # --- Part 9: revoke device-01 ---------------------------------------------

    smoke_log "revoking device-01 and confirming the broker now refuses it"
    (cd "$PKI" && ./04-revoke-cert.sh device-01 >/dev/null)
    docker compose -f "$SMOKE_LAB_DIR/docker-compose.yml" restart mosquitto >/dev/null
    wait_for_tcp localhost 8883 30

    # openssl verify intentionally exits non-zero for a revoked cert — that
    # IS the pass condition here, so capture the text first instead of
    # piping straight into grep (pipefail would otherwise turn openssl's
    # expected failure into the pipeline's exit status and mask a match).
    # This is the one step in the file with no live TLS peer to hand it an
    # intermediate certificate, so it uses CHAIN, not ROOT — see the note
    # above ROOT's definition.
    verify_out="$(openssl verify -crl_check \
        -CAfile <(cat "$PKI/intermediate-ca/crl/intermediate.crl.pem" "$CHAIN") \
        "$PKI/device-01.cert.pem" 2>&1 || true)"
    if grep -q "certificate revoked" <<<"$verify_out"; then
        smoke_log "OK — openssl verify confirms device-01 is on the CRL"
    else
        smoke_fail "device-01 not showing as revoked in the CRL"
    fi

    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" \
        -cert "$PKI/device-01.cert.pem" -key "$PKI/device-01.key.pem" \
        </dev/null >/dev/null 2>&1 || true
    sleep 1
    docker compose -f "$SMOKE_LAB_DIR/docker-compose.yml" logs mosquitto 2>/dev/null \
        | tail -5 | grep -q "certificate verify failed" \
        && smoke_log "OK — revoked device-01 refused by the broker" \
        || smoke_fail "revoked device-01 was NOT refused by the broker"

    # --- Part 10: verify device-02 still works --------------------------------

    smoke_log "checking device-02 (not revoked) still connects"
    timeout 5 openssl s_client -connect localhost:8883 -CAfile "$ROOT" \
        -cert "$PKI/device-02.cert.pem" -key "$PKI/device-02.key.pem" \
        </dev/null 2>&1 | grep -q "Verify return code: 0 (ok)" \
        && smoke_log "OK — device-02 unaffected by device-01's revocation" \
        || smoke_fail "device-02 was unexpectedly refused"
fi

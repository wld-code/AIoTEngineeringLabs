#!/usr/bin/env bash
# Smoke test — Lab 5: Device Twin (Mosquitto + Node-RED + Redis + FastAPI
# twin + Python device simulator).
#
# Default mode (no flags): validates docker-compose.yml syntax only.
# FULL=1: brings the stack up, exercises the real desired/reported loop
#         (apply a valid interval, apply an invalid one, confirm both are
#         reflected correctly), then tears down.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."
smoke_validate_compose

if smoke_full_mode; then
    smoke_compose_up
    trap smoke_compose_down EXIT

    wait_for_compose_healthy mosquitto  60
    wait_for_compose_healthy redis      60
    wait_for_compose_healthy twin-api   60
    wait_for_compose_healthy node-red   90
    wait_for_http http://localhost:8000/api/health 30
    wait_for_http http://localhost:1880/            30

    smoke_log "waiting for the simulator's telemetry to reach the twin API"
    ok=0
    for _ in $(seq 1 20); do
        body=$(curl -fsS http://localhost:8000/api/twin/sim-001 2>/dev/null || true)
        if [[ "$body" == *'"temperature_c"'* ]]; then
            ok=1
            break
        fi
        sleep 1
    done
    if [[ "$ok" -ne 1 ]]; then
        smoke_fail "no telemetry reached the twin API within 20s — check mosquitto/node-red/twin-api logs"
    fi
    smoke_log "telemetry flowing: $body"

    smoke_log "applying a valid desired interval (5s) and checking it is applied"
    curl -fsS -X POST http://localhost:8000/api/twin/sim-001/desired \
        -H 'Content-Type: application/json' -d '{"reporting_interval_s": 5}' >/dev/null
    applied=0
    for _ in $(seq 1 10); do
        status=$(curl -fsS http://localhost:8000/api/twin/sim-001 | python3 -c \
            'import json,sys; print(json.load(sys.stdin).get("command_status"))' 2>/dev/null || true)
        if [[ "$status" == "applied" ]]; then
            applied=1
            break
        fi
        sleep 1
    done
    if [[ "$applied" -ne 1 ]]; then
        smoke_fail "desired_interval=5 never reached command_status=applied (last seen: $status)"
    fi
    smoke_log "command_status=applied confirmed"

    smoke_log "applying an invalid desired interval (20s) and checking it is rejected"
    curl -fsS -X POST http://localhost:8000/api/twin/sim-001/desired \
        -H 'Content-Type: application/json' -d '{"reporting_interval_s": 20}' >/dev/null
    rejected=0
    for _ in $(seq 1 10); do
        status=$(curl -fsS http://localhost:8000/api/twin/sim-001 | python3 -c \
            'import json,sys; print(json.load(sys.stdin).get("command_status"))' 2>/dev/null || true)
        if [[ "$status" == "rejected" ]]; then
            rejected=1
            break
        fi
        sleep 1
    done
    if [[ "$rejected" -ne 1 ]]; then
        smoke_fail "desired_interval=20 never reached command_status=rejected (last seen: $status)"
    fi
    smoke_log "command_status=rejected confirmed"

    smoke_log "restarting device-simulator and confirming it reconnects"
    (cd "$SMOKE_LAB_DIR" && docker compose restart device-simulator >/dev/null)
    reconnected=0
    for _ in $(seq 1 15); do
        if (cd "$SMOKE_LAB_DIR" && docker compose logs device-simulator --since 20s 2>/dev/null) | grep -q "connected to broker"; then
            reconnected=1
            break
        fi
        sleep 1
    done
    if [[ "$reconnected" -ne 1 ]]; then
        smoke_fail "device-simulator did not log a reconnect after restart"
    fi
    smoke_log "device-simulator reconnected after restart"

    smoke_log "OK — telemetry flows end to end, valid/invalid desired-state commands both handled correctly, simulator reconnects after a restart"
fi

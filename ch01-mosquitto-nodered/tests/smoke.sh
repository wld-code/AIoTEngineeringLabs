#!/usr/bin/env bash
# Smoke test — Lab 1: Mosquitto + Node-RED + Streamlit on the canonical stack.
#
# Default mode (no flags): validates docker-compose.yml syntax only.
# FULL=1: brings the stack up, asserts the dashboard responds, tears down.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."
smoke_validate_compose

if smoke_full_mode; then
    smoke_compose_up
    trap smoke_compose_down EXIT
    wait_for_compose_healthy mosquitto 90
    wait_for_compose_healthy redis     90
    wait_for_compose_healthy nodered   90
    wait_for_compose_healthy streamlit 90
    wait_for_tcp  localhost 1883 60   # MQTT broker
    wait_for_tcp  localhost 6379 60   # Redis hot storage
    wait_for_http http://localhost:1880/ 60   # Node-RED editor
    wait_for_http http://localhost:8501/ 60   # Streamlit dashboard

    # nodered/data is bind-mounted, not a named volume, so a fresh clone
    # (or CI checkout) starts with no flow deployed — the reader's own
    # Part 2 (Menu > Import > Deploy) is a manual, one-time step this
    # automated check has to reproduce itself. Node-RED's Admin API takes
    # the same flow JSON the reader pastes into the Import dialog.
    smoke_log "deploying the flow via Node-RED's Admin API (the reader's own Import + Deploy, done non-interactively)"
    deploy_out=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:1880/flows \
        -H "Content-Type: application/json" \
        -H "Node-RED-Deployment-Type: full" \
        --data @"$SMOKE_LAB_DIR/nodered-flows/factory-flow.json")
    [[ "$deploy_out" == "204" ]] || smoke_fail "Node-RED flow deploy failed (HTTP $deploy_out)"
    smoke_log "OK — flow deployed"

    # Everything above only proves the containers started and their ports
    # answer — none of it proves a message actually flows publisher ->
    # Mosquitto -> Node-RED -> Redis. Run the real publisher briefly and
    # assert real device state lands in Redis, not just that the pipes
    # exist.
    smoke_log "publishing test telemetry and checking it reaches Redis"
    python3 -m venv "$SMOKE_LAB_DIR/.smoke_venv" >/dev/null
    "$SMOKE_LAB_DIR/.smoke_venv/bin/pip" install --quiet -r "$SMOKE_LAB_DIR/publisher/requirements.txt"
    ( cd "$SMOKE_LAB_DIR/publisher" && \
      MQTT_HOST=localhost PUBLISH_INTERVAL_S=0.5 timeout 8 \
      "$SMOKE_LAB_DIR/.smoke_venv/bin/python" sim_publisher.py >/dev/null 2>&1 ) || true
    rm -rf "$SMOKE_LAB_DIR/.smoke_venv"

    key_count=$(cd "$SMOKE_LAB_DIR" && docker compose exec -T redis redis-cli --no-raw KEYS "device:*" | wc -l | tr -d ' ')
    if [[ "$key_count" -lt 1 ]]; then
        smoke_fail "no device:* keys in Redis after publishing — pipeline is broken, not just unreachable"
    fi
    sample=$(cd "$SMOKE_LAB_DIR" && docker compose exec -T redis redis-cli GET "device:line-1/dev-01")
    if [[ "$sample" != *'"value"'* ]]; then
        smoke_fail "device:line-1/dev-01 did not contain the expected JSON shape: $sample"
    fi
    smoke_log "end-to-end OK — $key_count device keys in Redis, sample: $sample"

    smoke_log "OK — broker, Redis, editor and dashboard all respond, and telemetry actually flows end to end"
fi

#!/usr/bin/env bash
# Smoke test — Lab 3: protocol and connection overhead comparison.
#
# Default mode (no flags): validates docker-compose.yml syntax only.
# FULL=1: brings the stack up (including the client container), checks
#         basic connectivity, then runs the actual lab end to end via
#         run_all_tests.py and verifies its own "one TCP connection for
#         a persistent test" claim from the saved results — not just
#         that the containers started.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."
smoke_validate_compose

if smoke_full_mode; then
    smoke_compose_up
    trap smoke_compose_down EXIT
    wait_for_compose_healthy mosquitto    60
    wait_for_compose_healthy http_server  60
    wait_for_compose_healthy client       60
    wait_for_tcp  127.0.0.1 1883 30
    wait_for_tcp  127.0.0.1 8080 30

    smoke_log "checking the HTTP server accepts a POST and replies 204"
    status=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/telemetry \
             -H 'Content-Type: application/json' -d '{"device":"sensor-01","temp":23.7}')
    [[ "$status" == "204" ]] || smoke_fail "expected HTTP 204, got $status"

    smoke_log "checking MQTT delivers the same payload end to end"
    (
        sleep 1
        mosquitto_pub -h 127.0.0.1 -p 1883 -t 'lab/sensor-01/telemetry' \
            -m '{"device":"sensor-01","temp":23.7}'
    ) &
    got=$(timeout 6 mosquitto_sub -h 127.0.0.1 -p 1883 -t 'lab/sensor-01/telemetry' -C 1 2>/dev/null || true)
    wait
    [[ "$got" == '{"device":"sensor-01","temp":23.7}' ]] \
        || smoke_fail "MQTT round-trip did not return the expected payload: $got"

    smoke_log "running the full lab (capture + client, inside the client container) via run_all_tests.py"
    (cd "$SMOKE_LAB_DIR" && python3 run_all_tests.py) || smoke_fail "run_all_tests.py failed"

    smoke_log "checking Test B (persistent) really used exactly one TCP connection"
    flows=$(python3 -c "
import json
d = json.load(open('$SMOKE_LAB_DIR/results/results.json'))
print([r['tcp_flow_count'] for r in d['results'] if r['test'] == 'B'][0])
")
    [[ "$flows" == "1" ]] || smoke_fail "Test B used $flows TCP connections, expected 1"

    smoke_log "OK — broker and HTTP server both respond, the full lab runs end to end, connection reuse verified"
fi

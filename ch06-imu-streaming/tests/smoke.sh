#!/usr/bin/env bash
# Smoke test — Lab 6: IMU streaming through two Redpanda topics into TimescaleDB.
#
# This test only reaches the Redpanda + TimescaleDB half of the lab. Node-RED
# runs on the host (not in this compose file, see the README's "Why Node-RED
# runs on the host" note) and the Nano 33 BLE Sense is real hardware, neither
# is something a CI runner can bring up automatically. Bringing the two
# services up, creating both topics, and checking the DB schema is what is
# left to automate — it catches a broken init.sql or compose file before a
# reader ever plugs in a board.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."
smoke_validate_compose

if smoke_full_mode; then
    smoke_compose_up
    trap smoke_compose_down EXIT
    wait_for_tcp localhost 9092 60    # Redpanda, Kafka API
    wait_for_tcp localhost 5433 60    # TimescaleDB, host port 5433 not 5432, see docker-compose.yml

    smoke_log "waiting for Redpanda's own cluster health check"
    for _ in $(seq 1 30); do
        docker compose exec -T redpanda rpk cluster health 2>/dev/null | grep -q "Healthy:.*true" && break
        sleep 2
    done
    docker compose exec -T redpanda rpk cluster health 2>/dev/null | grep -q "Healthy:.*true" \
        || smoke_fail "Redpanda cluster never reported healthy"

    smoke_log "creating imu.raw and imu.alerts (idempotent — this is what the README's Part 2 also runs)"
    docker compose exec -T redpanda rpk topic create imu.raw --partitions 3 --replicas 1 >/dev/null 2>&1 || true
    docker compose exec -T redpanda rpk topic create imu.alerts --partitions 1 --replicas 1 >/dev/null 2>&1 || true
    topic_count=$(docker compose exec -T redpanda rpk topic list 2>/dev/null | grep -cE '^imu\.(raw|alerts)\s')
    [[ "$topic_count" == "2" ]] || smoke_fail "expected both imu.raw and imu.alerts to exist, found $topic_count"

    smoke_log "waiting for postgres to accept queries (the container restarts once internally after first-run initdb)"
    for _ in $(seq 1 30); do
        docker compose exec -T timescaledb pg_isready -U aiot -d aiot >/dev/null 2>&1 && break
        sleep 2
    done
    docker compose exec -T timescaledb pg_isready -U aiot -d aiot >/dev/null 2>&1 \
        || smoke_fail "postgres never became ready to accept queries"

    smoke_log "checking imu_samples and imu_alerts are both real hypertables, each with its own retention policy"
    for table in imu_samples imu_alerts; do
        hypertable_count=$(docker compose exec -T timescaledb psql -U aiot -d aiot -tAc \
            "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name = '${table}';")
        [[ "$hypertable_count" == "1" ]] || smoke_fail "${table} is not a hypertable (init.sql did not run cleanly)"

        retention_count=$(docker compose exec -T timescaledb psql -U aiot -d aiot -tAc \
            "SELECT count(*) FROM timescaledb_information.jobs WHERE application_name ILIKE 'Retention Policy%' AND hypertable_name = '${table}';")
        [[ "$retention_count" == "1" ]] || smoke_fail "no retention (TTL) policy attached to ${table}"
    done

    smoke_log "OK — Redpanda healthy with both topics, TimescaleDB up with both hypertables + TTL policies confirmed"
    smoke_log "not automated here: Node-RED (runs on the host) and the Nano 33 BLE Sense (real hardware)"
    smoke_log "follow the README's Procedure to verify the full serial -> Redpanda -> DB -> dashboard path by hand"
fi

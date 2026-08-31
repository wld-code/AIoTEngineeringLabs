#!/usr/bin/env bash
# Smoke test — Lab 2: RTOS latency on ESP32-S3 (firmware-only, self-measuring).
#
# This lab needs only a Seeed Studio XIAO ESP32-S3 + its USB-C cable: latency and CPU
# idle % are measured on-chip and printed over the serial monitor. No profiler,
# no logic analyser. Smoke checks both ESP-IDF projects are structurally sound
# and, in FULL mode, that the firmware builds — via PlatformIO (`pio`, no raw
# ESP-IDF install needed) if available, else via `idf.py` if that's on PATH.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../../../tests/_smoke_lib.sh"
smoke_lab_dir "$HERE/.."

# Both firmware variants are ESP-IDF projects (top-level CMakeLists + main/),
# each with a platformio.ini so PlatformIO can build them too.
projects=()
for proj in "$SMOKE_LAB_DIR/superloop" "$SMOKE_LAB_DIR/freertos"; do
    [[ -f "$proj/CMakeLists.txt" ]]        || smoke_fail "missing ${proj#$SMOKE_LAB_DIR/}/CMakeLists.txt"
    [[ -f "$proj/main/CMakeLists.txt" ]]   || smoke_fail "missing ${proj#$SMOKE_LAB_DIR/}/main/CMakeLists.txt"
    [[ -f "$proj/main/main.c" ]]           || smoke_fail "missing ${proj#$SMOKE_LAB_DIR/}/main/main.c"
    [[ -f "$proj/platformio.ini" ]]        || smoke_fail "missing ${proj#$SMOKE_LAB_DIR/}/platformio.ini"
    grep -q 'esp32s3' "$proj/sdkconfig.defaults" || smoke_fail "${proj#$SMOKE_LAB_DIR/} not targeting esp32s3"
    smoke_log "ESP-IDF project OK: ${proj#$SMOKE_LAB_DIR/}"
    projects+=("$proj")
done

if smoke_full_mode; then
    if command -v pio >/dev/null 2>&1; then
        for proj in "${projects[@]}"; do
            smoke_log "building ${proj#$SMOKE_LAB_DIR/} via pio (PlatformIO)"
            (cd "$proj" && pio run) || smoke_fail "pio build failed for ${proj#$SMOKE_LAB_DIR/}"
        done
        smoke_log "OK — both firmware variants compile"
    elif command -v idf.py >/dev/null 2>&1; then
        for proj in "${projects[@]}"; do
            smoke_log "building ${proj#$SMOKE_LAB_DIR/} via idf.py"
            (cd "$proj" && idf.py set-target esp32s3 >/dev/null && idf.py build) \
                || smoke_fail "idf.py build failed for ${proj#$SMOKE_LAB_DIR/}"
        done
        smoke_log "OK — both firmware variants compile"
    else
        smoke_skip "neither pio (pip install platformio) nor idf.py is on PATH"
    fi
else
    smoke_log "static mode — skipping build (run with FULL=1 + pio or ESP-IDF to compile)"
fi

smoke_log "on-device validation: flash, open the monitor, read the REPORT lines — see README"

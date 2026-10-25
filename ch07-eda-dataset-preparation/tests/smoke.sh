#!/usr/bin/env bash
# Smoke test — Lab 7: recorded sound dataset + EDA/windowing notebook.
#
# This lab has no Docker services: Node-RED runs on the host (it needs the
# board's USB serial port) and the notebook runs in a local virtual
# environment. What is left to automate is structural: the flow is valid,
# the shipped dataset is complete and the right shape, and — in FULL mode —
# the notebook actually executes end to end with no errors.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# Keep this lab's test standalone: this repository stores labs at its root,
# unlike the book repository's nested labs/ layout and shared test library.
smoke_full_mode() { [[ "${FULL:-0}" == "1" ]]; }
smoke_lab_dir() {
    SMOKE_LAB_DIR="$(cd "$1" && pwd)"
    SMOKE_LAB_NAME="$(basename "$SMOKE_LAB_DIR")"
}
smoke_log() { echo "  [smoke:$SMOKE_LAB_NAME] $*"; }
smoke_fail() {
    echo "  [smoke:$SMOKE_LAB_NAME] FAIL — $*" >&2
    exit 1
}

smoke_lab_dir "$HERE/.."

smoke_log "checking nodered/flows.json is valid JSON with no dangling references"
python3 - "$SMOKE_LAB_DIR/nodered/flows.json" <<'PY'
import json, sys
path = sys.argv[1]
nodes = json.load(open(path))
ids = {n["id"] for n in nodes}
missing = [n["id"] for n in nodes for wg in n.get("wires", []) for w in wg if w not in ids]
if missing:
    raise SystemExit(f"dangling wire references: {missing}")
dup = [i for i in ids if sum(1 for n in nodes if n["id"] == i) > 1]
if dup:
    raise SystemExit(f"duplicate node ids: {dup}")
print(f"  {len(nodes)} nodes, no dangling references, no duplicate ids")
PY

smoke_log "checking notebook/audio_eda.ipynb is valid notebook JSON"
python3 - "$SMOKE_LAB_DIR/notebook/audio_eda.ipynb" <<'PY'
import json, sys
nb = json.load(open(sys.argv[1]))
assert nb.get("nbformat") == 4, "unexpected nbformat"
cell_types = [c["cell_type"] for c in nb["cells"]]
assert "markdown" in cell_types and "code" in cell_types
print(f"  {len(nb['cells'])} cells")
PY

smoke_log "checking the shipped dataset: 4 categories, 5 recordings each, 9600 samples each"
python3 - "$SMOKE_LAB_DIR/data" <<'PY'
import csv, sys
from pathlib import Path

data_dir = Path(sys.argv[1])
categories = ["elektor", "electronics", "machines", "iot"]
total = 0
for category in categories:
    files = sorted((data_dir / category).glob(f"{category}_*.csv"))
    if len(files) != 5:
        raise SystemExit(f"{category}: expected 5 recordings, found {len(files)}")
    for f in files:
        with f.open() as fh:
            rows = list(csv.DictReader(fh))
        if len(rows) != 9600:
            raise SystemExit(f"{f}: expected 9600 rows, found {len(rows)}")
    total += len(files)
print(f"  {total} recordings, all 9600 samples")
PY

smoke_log "checking firmware and the recording driver are present"
[[ -f "$SMOKE_LAB_DIR/nano33-audio-capture/nano33-audio-capture.ino" ]] || smoke_fail "firmware sketch missing"
python3 -m py_compile "$SMOKE_LAB_DIR/record_dataset.py" || smoke_fail "record_dataset.py does not parse"

if smoke_full_mode; then
    smoke_log "executing the notebook end to end (this creates/reuses notebook/.venv)"
    (
        cd "$SMOKE_LAB_DIR/notebook"
        if [[ ! -d .venv ]]; then
            python3 -m venv .venv
            ./.venv/bin/pip install --quiet -r requirements.txt
            ./.venv/bin/pip install --quiet jupyter nbconvert ipykernel
        fi
        ./.venv/bin/jupyter nbconvert --to notebook --execute --output /tmp/lab7_smoke_executed.ipynb audio_eda.ipynb
    ) || smoke_fail "notebook execution failed"

    python3 - <<'PY'
import json
nb = json.load(open("/tmp/lab7_smoke_executed.ipynb"))
errors = [
    out for cell in nb["cells"] if cell["cell_type"] == "code"
    for out in cell.get("outputs", []) if out.get("output_type") == "error"
]
if errors:
    raise SystemExit(f"notebook raised an error: {errors[0]['ename']}: {errors[0]['evalue']}")
text = "\n".join(
    "".join(out.get("text", []))
    for cell in nb["cells"] if cell["cell_type"] == "code"
    for out in cell.get("outputs", []) if out.get("output_type") == "stream"
)
if "leave-one-out nearest-centroid agreement" not in text:
    raise SystemExit("expected result line not found in notebook output")
print("  notebook executed clean, no errors, final result present")
PY
    smoke_log "OK — notebook runs end to end with no errors"
else
    smoke_log "OK — structural checks passed (FULL=1 also executes the notebook)"
fi

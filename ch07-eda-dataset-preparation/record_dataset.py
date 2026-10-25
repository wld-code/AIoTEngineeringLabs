#!/usr/bin/env python3
"""Lab 7 — drives a full recording session against the Node-RED flow in
nodered/flows.json: for each of the four categories, fires the matching
"Record: <category>" inject node over Node-RED's HTTP API and, in the same
breath, speaks the word on the host machine's speaker (macOS `say`), so the
word and the board's capture window line up closely enough for the
firmware's 200ms pre-roll (see nano33-audio-capture.ino) to cover the gap.

This is how the 20 recordings shipped under data/ were made. It is not
required reading for the lab — clicking the four inject nodes by hand, as
the README's procedure describes, produces the same files. Read this script
if you want to record your own dataset without twenty manual clicks, or
with different words.

Requires: Node-RED already running with this lab's flow deployed, the
board flashed and connected, and (this script's own sound source) macOS,
since it shells out to `say`. On Linux or Windows, replace SPOKEN_WORD's
use in record_one() with another way to play a sound near the microphone.

Usage:
    python3 record_dataset.py
"""
import csv
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

INJECT_IDS = {
    "elektor": "7310i01",
    "electronics": "7310i02",
    "machines": "7310i03",
    "iot": "7310i04",
}
SPOKEN_WORD = {
    "elektor": "Elektor",
    "electronics": "Electronics",
    "machines": "Machines",
    "iot": "I O T",
}
REPS_PER_CATEGORY = 5
WEAK_PEAK_RMS_THRESHOLD = 150  # below this, the word was probably missed


def fire_inject(node_id: str) -> None:
    req = urllib.request.Request(f"http://127.0.0.1:1880/inject/{node_id}", method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def record_one(category: str, index: int, timeout_s: float = 40.0) -> Path:
    """Triggers one recording and waits for its CSV file to appear.

    Node-RED's own per-category counter (see the "start recording" function
    in nodered/flows.json) decides the file's actual name; this only
    computes the name it expects, to detect the file's arrival. Run this
    against a freshly (re)started Node-RED so its counters start at zero
    and match a run that starts index at 1 for every category.
    """
    target = DATA_DIR / category / f"{category}_{index:02d}.csv"
    before_mtime = target.stat().st_mtime if target.exists() else None

    fire_inject(INJECT_IDS[category])
    subprocess.Popen(["say", "-v", "Samantha", SPOKEN_WORD[category]])

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if target.exists():
            mtime = target.stat().st_mtime
            if before_mtime is None or mtime > before_mtime:
                time.sleep(0.3)  # let the write finish
                return target
        time.sleep(0.2)
    raise TimeoutError(f"{target} did not appear within {timeout_s:.0f}s")


def energy_profile(path: Path) -> tuple[int, float, float]:
    """Returns (sample count, overall RMS, peak 50ms-window RMS) — a quick
    check that a recording actually captured the word and is not silence."""
    with path.open() as f:
        vals = [int(row["amplitude"]) for row in csv.DictReader(f)]
    n = len(vals)
    overall_rms = (sum(v * v for v in vals) / n) ** 0.5 if n else 0.0
    chunk = 800  # 50ms at 16kHz
    peak_rms = 0.0
    for i in range(0, n, chunk):
        seg = vals[i : i + chunk]
        if not seg:
            continue
        rms = (sum(v * v for v in seg) / len(seg)) ** 0.5
        peak_rms = max(peak_rms, rms)
    return n, overall_rms, peak_rms


def main() -> None:
    results = []
    for category in INJECT_IDS:
        for i in range(1, REPS_PER_CATEGORY + 1):
            try:
                path = record_one(category, i)
            except TimeoutError as e:
                print(f"FAIL  {category} #{i:02d}: {e}", file=sys.stderr)
                results.append((category, i, None))
                continue
            n, overall, peak = energy_profile(path)
            flag = "OK  " if peak > WEAK_PEAK_RMS_THRESHOLD else "WEAK"
            print(f"{flag}  {category}_{i:02d}  n={n}  overall_rms={overall:6.1f}  peak_rms={peak:7.1f}")
            results.append((category, i, peak))
            time.sleep(0.5)

    weak = [r for r in results if r[2] is not None and r[2] <= WEAK_PEAK_RMS_THRESHOLD]
    print(f"\n--- recordings at or below peak_rms {WEAK_PEAK_RMS_THRESHOLD} (likely missed the word) ---")
    print("none" if not weak else "\n".join(f"{c}_{i:02d}" for c, i, _ in weak))


if __name__ == "__main__":
    main()

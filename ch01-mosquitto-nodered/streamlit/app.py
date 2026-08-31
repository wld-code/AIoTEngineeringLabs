"""
Lab 1 — Streamlit dashboard.

Reads live state *from Redis only*. It never connects to the MQTT broker.
Node-RED is the producer, Streamlit is one consumer, and Redis is the shared
state layer between them — exactly the decoupling Chapter 1 argues for. Swap
this dashboard for an ERP exporter and nothing else in the platform changes.

Redis layout written by the Node-RED flow:
  device:<line>/<dev>   string  ->  {"line","device","value","unit","ts"}
  alarms                list    ->  newest-first JSON alarm records
"""
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime

import pandas as pd
import plotly.express as px
import redis
import streamlit as st

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
KEEP_SAMPLES = 1200          # rolling chart window, per device
STALE_AFTER_S = 10           # no fresh Redis state for this long => stale
REFRESH_S = 2

state = st.session_state
state.setdefault("history", defaultdict(lambda: deque(maxlen=KEEP_SAMPLES)))
state.setdefault("last_ts", {})   # device -> last unix_ms already charted


@st.cache_resource
def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        decode_responses=True, socket_timeout=2,
    )


def read_live_state(r: redis.Redis) -> list[dict]:
    """One snapshot of every device's latest reading from Redis."""
    devices = []
    for key in r.scan_iter(match="device:*", count=100):
        raw = r.get(key)
        if not raw:
            continue
        try:
            devices.append(json.loads(raw))
        except ValueError:
            continue
    return devices


def read_alarms(r: redis.Redis, n: int = 50) -> list[dict]:
    out = []
    for raw in r.lrange("alarms", 0, n - 1):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


st.set_page_config(page_title="Lab 1 — live telemetry", layout="wide")
st.title("Live telemetry — Node-RED → Redis → Streamlit")

r = get_redis()
try:
    r.ping()
    snapshot = read_live_state(r)
    alarms = read_alarms(r)
    connected = True
except (redis.exceptions.RedisError, OSError) as exc:
    connected = False
    snapshot, alarms = [], []
    st.error(f"Redis unreachable at {REDIS_HOST}:{REDIS_PORT} — {exc}")

now_ms = int(time.time() * 1000)

# Fold this snapshot into the rolling per-device history. We only append when
# the device's timestamp advanced, so a stopped publisher freezes the chart
# instead of drawing a flat line of repeated points.
fresh_devices = 0
for d in snapshot:
    dev = f"{d.get('line')}/{d.get('device')}"
    ts = int(d.get("ts", 0))
    value = d.get("value")
    if value is None:
        continue
    if state["last_ts"].get(dev) != ts:
        state["history"][dev].append((datetime.fromtimestamp(ts / 1000), float(value)))
        state["last_ts"][dev] = ts
    if now_ms - ts <= STALE_AFTER_S * 1000:
        fresh_devices += 1

c1, c2, c3 = st.columns(3)
c1.metric("Devices in Redis", len(snapshot))
c2.metric("Fresh (< 10 s)", fresh_devices)
c3.metric("Alarms stored", len(alarms))

if connected and snapshot and fresh_devices == 0:
    st.warning(
        "No fresh state reaching Redis — is the publisher running? "
        "The dashboard freezes because Node-RED has nothing new to store."
    )

rows = []
for dev, samples in state["history"].items():
    for ts, value in samples:
        rows.append({"ts": ts, "device": dev, "value": value})

if rows:
    df = pd.DataFrame(rows)
    fig = px.line(df, x="ts", y="value", color="device",
                  title="Temperature (°C) — live, from Redis")
    fig.update_layout(legend_orientation="h", legend_y=-0.25)
    st.plotly_chart(fig, use_container_width=True)
elif connected:
    st.info("Waiting for the first device state in Redis… start the publisher.")

st.subheader(f"Recent alarms ({len(alarms)})")
if alarms:
    st.dataframe(pd.DataFrame(alarms), use_container_width=True)
else:
    st.write("None.")

time.sleep(REFRESH_S)
st.rerun()

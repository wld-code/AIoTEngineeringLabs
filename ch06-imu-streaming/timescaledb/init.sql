-- Lab 6 — TimescaleDB schema for the Nano 33 BLE Sense's IMU stream.
-- Loaded automatically on first start by the docker-entrypoint-initdb.d hook.
--
-- Two hypertables, one per Redpanda topic, one per Node-RED consumer:
--   imu_samples  <- topic imu.raw     (every sample, the raw stream)
--   imu_alerts   <- topic imu.alerts  (only the samples a rolling-window
--                                      vibration check actually flagged)
-- They are independent tables on purpose, not a `severity` column on one
-- table: imu_samples exists to answer "what did the sensor read", imu_alerts
-- exists to answer "when did something worth a human's attention happen",
-- and those two questions want different retention, different row volume,
-- and a consumer that can fail or fall behind without touching the other.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw triaxial accelerometer samples, one row per message the raw-stream
-- consumer reads off Redpanda topic imu.raw. `device` stays a column, not a
-- fixed value, so a second board can publish onto the same table without a
-- schema change.
CREATE TABLE IF NOT EXISTS imu_samples (
    ts      TIMESTAMPTZ NOT NULL,
    device  TEXT        NOT NULL,
    ax      REAL,
    ay      REAL,
    az      REAL,
    mag_g   REAL
);

SELECT create_hypertable('imu_samples', 'ts',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Unique on (device, ts): the natural query index, and it makes a Node-RED
-- flow that reconnects and briefly re-sends the same samples a no-op rather
-- than duplicate rows, if the insert query uses ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX IF NOT EXISTS idx_imu_device_ts
    ON imu_samples (device, ts DESC);

-- Continuous aggregate: 1-second mean per axis per device. The dashboard
-- reads this view, never the raw table, so it stays fast no matter how long
-- the board has been streaming.
CREATE MATERIALIZED VIEW IF NOT EXISTS imu_1s
    WITH (timescaledb.continuous) AS
SELECT time_bucket('1 second', ts) AS bucket,
       device,
       avg(ax)::REAL AS ax_mean,
       avg(ay)::REAL AS ay_mean,
       avg(az)::REAL AS az_mean,
       count(*)      AS n_samples
FROM imu_samples
GROUP BY bucket, device
WITH NO DATA;

SELECT add_continuous_aggregate_policy('imu_1s',
    start_offset => INTERVAL '5 minutes',
    end_offset   => INTERVAL '10 seconds',
    schedule_interval => INTERVAL '10 seconds');

-- TTL: this is what keeps the database from growing without bound while the
-- board streams continuously. A background job drops whole chunks (not
-- row-by-row deletes) once they age past the interval below. Raw samples
-- expire after 24 hours, the 1-second aggregate is kept for 30 days.
-- Tighter than Chapter 6's 50-device fleet numbers on purpose: one real
-- board streaming for days on a laptop should not quietly fill the disk.
SELECT add_retention_policy('imu_samples', INTERVAL '24 hours');
SELECT add_retention_policy('imu_1s',      INTERVAL '30 days');

-- Compression: chunks older than 6 hours convert to columnar storage before
-- they age out entirely. On one board's worth of data this mostly matters
-- as a demonstration of the policy, not as a space saving you will notice.
ALTER TABLE imu_samples SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('imu_samples', INTERVAL '6 hours');

-- Alerts: one row per message the alerts-stream consumer reads off Redpanda
-- topic imu.alerts, i.e. only the samples the Node-RED analysis function
-- flagged as a peak-to-peak swing over its rolling-window threshold. Low
-- volume by design, a real vibration event should be rare, so it earns a
-- longer retention than the raw table: a week of alerts is worth keeping
-- around to look at, a week of every raw sample is not.
CREATE TABLE IF NOT EXISTS imu_alerts (
    ts              TIMESTAMPTZ NOT NULL,
    device          TEXT        NOT NULL,
    peak_to_peak_g  REAL        NOT NULL,
    mag_g           REAL,
    threshold_g     REAL,
    ax              REAL,
    ay              REAL,
    az              REAL
);

SELECT create_hypertable('imu_alerts', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_imu_alerts_device_ts
    ON imu_alerts (device, ts DESC);

SELECT add_retention_policy('imu_alerts', INTERVAL '7 days');

-- Lab 6 — query speedup benchmark.
-- Compares an aggregate query against the raw hypertable vs the continuous aggregate.

\timing on

\echo '== Raw hypertable: 5-minute mean over the last hour =='
EXPLAIN (ANALYZE, BUFFERS)
SELECT time_bucket('5 minutes', ts) AS bucket,
       device,
       avg(ax) ax, avg(ay) ay, avg(az) az
FROM imu_samples
WHERE ts > now() - INTERVAL '1 hour'
GROUP BY bucket, device
ORDER BY bucket;

\echo ''
\echo '== Continuous aggregate: same window, same answer =='
EXPLAIN (ANALYZE, BUFFERS)
SELECT time_bucket('5 minutes', bucket) AS bucket5,
       device,
       avg(ax_mean) ax, avg(ay_mean) ay, avg(az_mean) az
FROM imu_1s
WHERE bucket > now() - INTERVAL '1 hour'
GROUP BY bucket5, device
ORDER BY bucket5;

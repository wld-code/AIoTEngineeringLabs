# Data Processing Technologies

[Back to Lab 6](../ch06-imu-streaming/README.md)

Lab 6 puts two data-processing technologies to work: Redpanda, a Kafka-compatible streaming broker, and TimescaleDB, a time-series extension for PostgreSQL. This page is a technical introduction to both — what each one is, how it stores and moves data internally, and the schemas and commands you use to operate it. It is not a lab procedure. For the commands that actually bring Lab 6 up, follow [the lab's own README](../ch06-imu-streaming/README.md).

## Part 1 — Kafka and Redpanda

### What "Kafka" means here

Apache Kafka is really two things bundled together: a **protocol** — the wire format and semantics of topics, partitions, offsets, and consumer groups — and a **reference implementation** of that protocol, written in Java, historically coordinated by ZooKeeper and more recently by Kafka's own built-in Raft mode (KRaft).

Redpanda implements the same wire protocol in C++, from scratch, with no JVM and no ZooKeeper. A client library, or a CLI, that only knows how to speak "Kafka" — produce a batch, fetch from an offset, join a consumer group — cannot tell the difference between talking to Kafka and talking to Redpanda. That is why this lab's Node-RED nodes use KafkaJS, a Kafka client library, against a Redpanda broker: nothing in KafkaJS is Redpanda-specific.

### Architecture: how a partition actually gets written and replicated

- **Broker.** One Redpanda process, holding a subset of the cluster's partitions. This lab runs a single broker in Docker; a production cluster runs several.
- **Topic.** A named, ordered, append-only log. This lab uses two: `imu.raw` and `imu.alerts`.
- **Partition.** A topic is split into one or more partitions, each an independent ordered log with its own offsets starting at 0. A partition is the unit of both ordering and parallelism — order is guaranteed only within a partition, never across partitions of the same topic. `imu.raw` has 3 partitions in this lab; `imu.alerts` has 1.
- **Segment.** On disk, a partition's log is not one file. It is a sequence of segment files, rolled over once a segment hits a size or age limit. Every segment but the active one is immutable. Retention and compaction both act on whole segments, which is why dropping old data is cheap: it is a file deletion, not a row-by-row scan.
- **Replication via Raft.** This is the core architectural difference from classic Kafka. Kafka coordinates replica state through a separate controller (formerly backed by a ZooKeeper ensemble, now by a KRaft quorum). Redpanda instead makes **each partition its own Raft group**. One replica is the Raft leader for that partition; the others are followers that replicate its log entries. Leader election, on a broker failing, is handled by that partition's own Raft group — there is no cluster-wide single point of coordination for data partitions. Redpanda's internal cluster metadata (topic configs, broker membership) is itself stored in an internal Raft group, so the whole system needs no ZooKeeper and no separate consensus service.
- **Thread-per-core execution.** Redpanda is built on the Seastar framework: each CPU core runs its own share of partitions as an independent shard, with its own memory and its own I/O queue, communicating with other cores through explicit message passing rather than shared-memory locks. This is why Redpanda scales close to linearly with cores added, and why it needs no JVM garbage collector tuning — there is no JVM.

### The produce and fetch path

Producing a message: the client sends a batch of records to the partition's current leader. The leader appends the batch to its local log, then replicates it to followers through Raft. Once the number of replicas required by the producer's `acks` setting have confirmed the write, the leader acknowledges the produce request back to the client.

- `acks=0` — the client does not wait for any confirmation. Fastest, and a broker or network failure can silently drop the message.
- `acks=1` — the client waits for the partition leader to append the record locally. A leader failure before replication can still lose it.
- `acks=all` (or `-1`) — the client waits for the write to be committed by a Raft majority of replicas. This is the durable setting, and the one this lab's producer uses implicitly through KafkaJS's defaults for a healthy cluster.

Consuming a message: a consumer sends a fetch request naming a partition and an offset. The broker returns the log bytes for every record at or after that offset, up to a size limit. Nothing is pushed to consumers — every fetch is the consumer asking for more, which is why a slow consumer never blocks a fast producer.

### Anatomy of a record

Every record written to a partition carries the same fields, regardless of what your application puts in them:

| Field | Meaning |
| :---- | :---- |
| `key` | Optional bytes. Used to choose a partition — see below — and, on a compacted topic, to identify which records supersede which. |
| `value` | The payload, opaque bytes to the broker. This lab's value is a UTF-8 JSON document. |
| `headers` | Optional key/value metadata pairs, carried alongside the record but outside `value`. |
| `timestamp` | Set by the producer (event time) or the broker (log-append time), depending on topic configuration. |
| `partition` | Which partition the record landed in. |
| `offset` | The record's position within that partition, assigned by the broker on append, never reused. |

The broker enforces nothing about the shape of `value`. A schema is a contract your producers and consumers agree to, not something Redpanda checks by default (a Schema Registry, which Redpanda also ships, can enforce one — this lab does not run it, and relies on every Node-RED flow agreeing on the JSON shape by convention instead). The two schemas actually produced in this lab:

```jsonc
// imu.raw — one per measurement, key = device name
{
  "device": "nano-01",
  "ts": 1717000000000,   // epoch milliseconds, set by Node-RED
  "ax": 0.012, "ay": -0.003, "az": 0.998,   // g
  "gx": 1.4, "gy": -0.2, "gz": 0.1          // deg/s
}
```

```jsonc
// imu.alerts — one per threshold crossing, key = device name
{
  "device": "nano-01",
  "ts": 1717000005231,
  "peak_to_peak_g": 0.63,   // window's max minus min magnitude, see below
  "threshold_g": 0.5
}
```

### Partitioning: which key goes to which partition

When a record carries a key, the client hashes it and maps that hash to one of the topic's partitions; the same key always lands on the same partition, for as long as the partition count does not change. A keyless record is spread across partitions round-robin instead. This lab keys every record by device name, `nano-01`. With one device, every record therefore carries the same key and lands on a single partition of `imu.raw` — 3 partitions doesn't mean 3-way parallelism here, it means headroom for more devices later, each hashing to a (not necessarily distinct) partition of its own.

### Consumer groups, offsets, and lag

A **consumer group** is a named set of consumers that divide a topic's partitions between them, so that within one group each partition is read by exactly one consumer at a time. Redpanda's group coordinator assigns partitions to group members and reassigns them — a rebalance — when a member joins or leaves. This lab defines two groups: `ts-writer`, reading `imu.raw` into TimescaleDB, and `alert-writer`, reading `imu.alerts`. (Node-RED's Kafka client library prefixes every group id it creates, so `ts-writer` is visible on the broker as `nodered_hm_kafka_client_ts-writer`.)

An **offset** is a consumer's position in a partition — the index of the next record it will read. A **committed offset** is the last position a group has recorded as processed; restarting a consumer resumes from there, not from the start of the topic. Committing an offset confirms only that the record was read, not that everything the consumer did with it afterwards — such as inserting a row into TimescaleDB — succeeded. Nothing about the commit is transactional with that side effect unless you explicitly make it so.

**Lag** is `highest offset written to a partition − group's committed offset`. Lag near zero means the consumer is keeping up; growing lag means the producer is outrunning it.

### `rpk`: the command-line tool

`rpk` is Redpanda's own CLI, talking to the broker's Kafka API and its Admin API. The commands relevant to this lab:

```bash
# Cluster and broker health
rpk cluster info
rpk cluster health

# Topics
rpk topic create imu.raw --partitions 3 --replicas 1
rpk topic create imu.alerts --partitions 1 --replicas 1
rpk topic list
rpk topic describe imu.raw
rpk topic alter-config imu.raw --set retention.ms=86400000

# Reading and writing directly, for debugging
rpk topic produce imu.raw          # type a JSON line, Enter, Ctrl+D
rpk topic consume imu.raw --offset start
rpk topic consume imu.alerts --offset end   # only new messages

# Consumer groups
rpk group list
rpk group describe nodered_hm_kafka_client_ts-writer
```

`rpk topic describe` reports partition count, replication factor, and per-partition leader; `rpk group describe` reports, per partition, the current offset, the log-end offset, and the lag between them — the same lag defined above, read directly off the broker instead of computed by hand.

### Retention and compaction

Two independent mechanisms remove data from a topic, and this lab's Redpanda topics use neither explicitly — they're left at Redpanda's defaults, which is worth naming precisely because TimescaleDB, below, is configured deliberately the opposite way.

- **Retention** deletes whole segments once every record in them is older than a configured window (`retention.ms`) or the partition exceeds a size limit (`retention.bytes`). This is what most topics use: a bounded window of history, oldest data dropped first.
- **Compaction** (`cleanup.policy=compact`) instead keeps only the latest record per key, forever, dropping older records with the same key once a segment is compacted. It turns a topic into something closer to a changelog of current state per key than a time-bounded event history. Neither `imu.raw` nor `imu.alerts` uses this — every record is a distinct measurement, not a key's current value.

## Part 2 — TimescaleDB

### What it is

TimescaleDB is an extension loaded into an ordinary PostgreSQL server, not a forked or separate database engine. Every normal PostgreSQL feature — SQL, `JOIN`s, indexes, `psql`, your existing drivers — works unchanged. What the extension adds is automatic time-based partitioning and operations built for time series, under a table type it calls a **hypertable**.

### Hypertables and chunks

A hypertable looks like one ordinary table to every query and insert. Internally, TimescaleDB splits it into **chunks**, each holding the rows for one time range, and routes every insert to the right chunk automatically. A query that only touches a recent time range only has to scan the chunks that overlap it — chunk exclusion — rather than the whole table.

```sql
-- imu_samples: one row per accepted measurement
CREATE TABLE imu_samples (
    ts       TIMESTAMPTZ NOT NULL,
    device   TEXT NOT NULL,
    ax       DOUBLE PRECISION,
    ay       DOUBLE PRECISION,
    az       DOUBLE PRECISION,
    gx       DOUBLE PRECISION,
    gy       DOUBLE PRECISION,
    gz       DOUBLE PRECISION,
    UNIQUE (device, ts)
);
SELECT create_hypertable('imu_samples', 'ts', chunk_time_interval => INTERVAL '1 hour');

-- imu_alerts: one row per threshold crossing
CREATE TABLE imu_alerts (
    ts             TIMESTAMPTZ NOT NULL,
    device         TEXT NOT NULL,
    peak_to_peak_g DOUBLE PRECISION,
    threshold_g    DOUBLE PRECISION,
    UNIQUE (device, ts)
);
SELECT create_hypertable('imu_alerts', 'ts', chunk_time_interval => INTERVAL '1 day');
```

`create_hypertable` takes an existing table and a time column, and requires that column be part of every uniqueness constraint on the table — TimescaleDB cannot enforce a `UNIQUE` or primary key across chunks unless the partitioning column is part of it. The `UNIQUE (device, ts)` constraint above is also what makes this lab's `INSERT ... ON CONFLICT DO NOTHING` safe against Redpanda re-delivering a record already consumed: the insert becomes a no-op instead of a duplicate row.

`imu_samples` uses 1-hour chunks, `imu_alerts` uses 1-day chunks — a chunk interval should keep each chunk's *indexes* comfortably in memory, so a high-volume table gets a shorter interval than a low-volume one.

### Retention: dropping chunks, not rows

A **retention policy** is a background job, scheduled inside the database itself, that drops whole chunks once every row in them is older than a window:

```sql
SELECT add_retention_policy('imu_samples', INTERVAL '24 hours');
SELECT add_retention_policy('imu_alerts', INTERVAL '7 days');
```

Because a chunk is a physical partition, dropping it is a metadata operation, not a `DELETE` that has to find and remove matching rows one at a time — the same reason Redpanda's segment-based retention, above, is cheap. This is entirely independent of Redpanda's own topic retention: the broker and the database each decide, on their own configured windows, when their copy of the data is gone.

### Compression and continuous aggregates

Two more hypertable features worth knowing even though this lab's tables run too short a retention window to need them:

- **Native compression** converts older chunks to a columnar, compressed layout — good for a table whose recent data is queried often (row-oriented, uncompressed) and whose old data is queried rarely (column-oriented, compressed). Enabled per hypertable and applied by a policy, the same way retention is:
  ```sql
  ALTER TABLE imu_samples SET (timescaledb.compress, timescaledb.compress_segmentby = 'device');
  SELECT add_compression_policy('imu_samples', INTERVAL '6 hours');
  ```
- **Continuous aggregates** are materialized views that TimescaleDB keeps incrementally up to date, rather than recomputing from scratch — useful for a rollup like "average acceleration magnitude per device per minute" that would otherwise mean rescanning raw rows on every dashboard refresh.
  ```sql
  CREATE MATERIALIZED VIEW imu_samples_1m
  WITH (timescaledb.continuous) AS
  SELECT device, time_bucket('1 minute', ts) AS bucket,
         avg(sqrt(ax*ax + ay*ay + az*az)) AS avg_magnitude
  FROM imu_samples
  GROUP BY device, bucket;
  ```

### Inspecting a hypertable

```sql
-- Chunks backing a hypertable, and their time ranges
SELECT show_chunks('imu_samples');
SELECT * FROM timescaledb_information.chunks
  WHERE hypertable_name = 'imu_samples';

-- Configured jobs (retention, compression, continuous aggregate refresh)
SELECT * FROM timescaledb_information.jobs;

-- Ordinary PostgreSQL introspection still works
\d+ imu_samples
```

## How the two fit together

Redpanda and TimescaleDB solve different problems and neither substitutes for the other. Redpanda is a durable, ordered, replayable log: many consumers can read the same data independently, at their own pace, and a new consumer can replay history from any retained offset. It has no query language and no concept of "the current state of device nano-01" beyond "the last record on its partition." TimescaleDB is the opposite: a queryable, indexed, aggregatable store of current and historical state, with no built-in notion of independent replay for multiple readers. The usual shape, and this lab's shape, is a small bridge — a consumer group — that reads once from the log and writes once into the database, so each technology is doing only the part it is actually good at.

## References

- [Redpanda architecture: Raft consensus](https://docs.redpanda.com/current/get-started/architecture/)
- [Redpanda: the Seastar thread-per-core model](https://docs.redpanda.com/current/get-started/architecture/#thread-per-core)
- [`rpk` command reference](https://docs.redpanda.com/current/reference/rpk/)
- [KafkaJS, consuming messages and offsets](https://kafka.js.org/docs/consuming)
- [KafkaJS, producing messages and partitioning](https://kafka.js.org/docs/producing)
- [TimescaleDB, hypertables and chunks](https://docs.timescale.com/use-timescale/latest/hypertables/)
- [TimescaleDB, data retention](https://docs.timescale.com/use-timescale/latest/data-retention/)
- [TimescaleDB, compression](https://docs.timescale.com/use-timescale/latest/compression/)
- [TimescaleDB, continuous aggregates](https://docs.timescale.com/use-timescale/latest/continuous-aggregates/)

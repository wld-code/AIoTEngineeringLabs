# Lab 6: Streaming Technologies

[Back to Lab 6](../ch06-imu-streaming/README.md)

This page explains the technologies used in Lab 6 and the terms its procedure relies on. It does not repeat the installation or run commands. Follow the lab's own README for those.

## Technologies used

| Technology | Role in this lab |
| :---- | :---- |
| Arduino Nano 33 BLE Sense | Reads acceleration from its onboard LSM9DS1 sensor and sends it over USB. |
| USB serial and JSON | Carries one JSON object per line from the board to Node-RED. No other protocol runs between the board and the host. |
| Node-RED | Runs every step that is not on the board or in a database: decoding, vibration analysis, producing to Redpanda, consuming from Redpanda, writing to TimescaleDB, and serving the dashboard. |
| Redpanda | A broker that speaks the Kafka wire protocol. It stores this lab's two topics as ordered, replayable logs. |
| KafkaJS, through `@oriolrius/node-red-contrib-kafka` | The Node-RED nodes that produce to and consume from Redpanda use the KafkaJS client library internally. This is the package actually installed in `nodered/package.json`. |
| `rpk` | Redpanda's command-line tool, used from a terminal to inspect topics and consumer groups. |
| PostgreSQL with the TimescaleDB extension | Stores measurements and alerts as SQL tables, extended with hypertables and retention policies. |
| FlowFuse Dashboard | The Node-RED dashboard library that serves the page at `/dashboard/lab6`. |
| Docker Compose | Runs Redpanda and TimescaleDB as containers, defined in `docker-compose.yml`. |

Redpanda is the only broker in this lab. It implements the same wire protocol as Apache Kafka, which is why its client library, and `rpk`, behave like Kafka tools. Running them does not start or require a separate Apache Kafka service.

Two services run in Docker: `redpanda` and `timescaledb`. Node-RED is not a third container. It runs as a process on the host machine, started directly with `node-red`, because it needs access to the board's USB serial port, which Docker does not pass through to a container on most systems.

## Topics and consumer groups

A topic is an ordered, append-only log. This lab uses two: `imu.raw`, created with 3 partitions, and `imu.alerts`, created with 1 partition.

A partition is one ordered subdivision of a topic. Kafka assigns a message to a partition based on its key, and messages sharing a key always go to the same partition. Every message in this lab is keyed by device name, `nano-01`. With one device, every message carries the same key and lands on a single partition. Which partition that is depends on the key's hash, not on the order devices are added. A second device's key is not guaranteed to land on a different partition than the first.

A consumer group is a named set of consumers reading a topic together. This lab defines two: `ts-writer`, reading `imu.raw` into `imu_samples`, and `alert-writer`, reading `imu.alerts`. Node-RED's Kafka client library names each group `nodered_hm_kafka_client_<name>`, so `ts-writer` appears as `nodered_hm_kafka_client_ts-writer` in `rpk group describe`.

An offset is a consumer's position in a partition, the index of the next message it will read. A committed offset is the last position a consumer group has recorded. Restarting a consumer resumes from its group's last committed offset, rather than from the start of the topic.

Lag is the difference between the highest offset written to a partition and a consumer group's committed offset. `rpk group describe` reports it. Lag near zero means the consumer is keeping up with the producer.

A committed offset confirms that the consumer has read a message. It does not confirm that everything the consumer does with that message, such as inserting a row into TimescaleDB, has completed or succeeded. This lab's client library commits offsets as it reads, independently of the database write that follows. The unique index and `ON CONFLICT DO NOTHING` clause on both TimescaleDB tables make a duplicate insert harmless if a message is read again. They do not recover an insert that never happened.

## Vibration processing

Node-RED keeps a sliding window of the last 20 acceleration-magnitude readings for each device, roughly 170 ms of data at the LSM9DS1's own output rate near 119 Hz. The magnitude is `sqrt(ax² + ay² + az²)`, in g, which sits near 1 at rest because it includes gravity.

On every new measurement, Node-RED computes the window's peak-to-peak spread, its maximum minus its minimum. If that spread exceeds 0.5 g, and at least 2 seconds have passed since the last alert for that device, Node-RED produces one alert message. The threshold and the cooldown are both set in the `analyze vibration, shape for Redpanda` function node in flow tab 1, and can be changed there.

This analysis runs before either topic. `imu.raw` and `imu.alerts` are two separate outputs of the same function, not one topic filtered by a downstream consumer.

## Time series storage

TimescaleDB extends PostgreSQL with hypertables. A hypertable behaves like an ordinary table for queries and inserts, and is internally split into chunks by time range. This lab creates two: `imu_samples`, with 1-hour chunks, and `imu_alerts`, with 1-day chunks.

A retention policy is a scheduled background job that drops chunks once every row in a chunk is older than a configured window. `imu_samples` has a 24-hour window, `imu_alerts` has a 7-day window. Dropping a chunk removes many rows at once. It does not run as a row-by-row delete.

This retention applies to the TimescaleDB tables. It is separate from any retention configured on the Redpanda topics themselves, which this lab leaves at Redpanda's default.

## Dashboard data paths

The dashboard shows the same kind of event two different ways.

The Telemetry and Stored alerts groups read from TimescaleDB on a timer, one second and five seconds respectively. Each read is a plain SQL query against the current table contents.

The Live alerts group is different. The alert consumer in flow tab 3 sends each alert to the dashboard widget directly, in the same step where it inserts the row into `imu_alerts`. No database read is involved in that path. The widget keeps its rows in Node-RED's own memory, which is why reloading the dashboard page does not clear it, but restarting Node-RED does.

## References

- [Node-RED, supported Node.js versions](https://nodered.org/docs/getting-started/local)
- [KafkaJS, consuming messages and offsets](https://kafka.js.org/docs/consuming)
- [KafkaJS, producing messages and partitioning](https://kafka.js.org/docs/producing)
- [TimescaleDB, data retention](https://docs.timescale.com/use-timescale/latest/data-retention/)

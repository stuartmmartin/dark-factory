# ADR-0009: apache/kafka KRaft in dev/CI, confluent-kafka client

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
The transactional outbox/inbox pattern (ADR-0010) and idempotent event delivery depend on
production-faithful Kafka semantics (exactly the producer idempotence and consumer-group behavior
that a fake or simplified broker can get subtly wrong). We need a broker to run in `docker compose`
for local dev and in CI via testcontainers, and a Python client library. Options for the broker
were a legacy ZooKeeper-based Kafka image versus the newer KRaft (no ZooKeeper) mode; options for
the client were `kafka-python` (pure Python) versus `confluent-kafka` (a `librdkafka` binding).

## Decision
Dev and CI run `apache/kafka` 4.x in single-node **KRaft** mode (no ZooKeeper), with topic
auto-create disabled — topics are created by an init container from the `contracts/events` schema
directory, so dev/CI topics always match the committed contracts (spec §5.1). The Python client is
**confluent-kafka**, used for both producing (the outbox relay, with `enable.idempotence=true`)
and consuming (spec §10).

## Consequences
KRaft matches where Kafka itself is heading and removes a whole appliance (ZooKeeper) from
`docker compose`, simplifying `make up infra` and `make doctor`. `confluent-kafka`'s `librdkafka`
core is the most production-proven client for the idempotent-producer and consumer-group behavior
the outbox/inbox pattern relies on, at the cost of a compiled dependency (wheels handle this on
supported platforms, but it's a heavier install than a pure-Python client) and an API that is
lower-level and less Pythonic than `kafka-python`'s.

## Revisit when
`librdkafka` wheels stop being available for a platform the team needs (e.g. a new CPU
architecture), or Confluent's client licensing or maintenance posture changes in a way that makes
a pure-Python client the safer default.

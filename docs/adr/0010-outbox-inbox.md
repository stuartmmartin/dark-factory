# ADR-0010: Transactional outbox and inbox for events

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Once business logic writes to Postgres and also needs to publish an event (e.g. `post_journal_entry`
must both persist the journal entry and emit `JournalEntryPosted`, spec §6.2 R4), a dual-write to
the database and the broker in two separate operations can fail halfway, leaving the database and
the event stream disagreeing about what happened — with no way to tell which one is right after
the fact. Consumers of those events also need to handle Kafka's at-least-once delivery without
double-applying an effect on a redelivered message.

## Decision
Producers never publish to Kafka directly inside a use case. A use case writes its event to an
`outbox` table (`id, tenant, topic, key, payload, headers, created_at, published_at`) in the same
database transaction as its business writes. A separate relay process polls the outbox with
`FOR UPDATE SKIP LOCKED` and publishes to Kafka with `enable.idempotence=true`, marking
`published_at` once sent (spec §10). Consumers are made idempotent through an `inbox` table
(`consumer, message_id`, unique key): a consumer checks the inbox before applying an effect and
records the message id atomically with that effect, so a redelivered message produces one effect,
not two (spec §6.4's `journal_entry_posted_logger` is the worked example).

## Consequences
The database write and the "an event will eventually be published" fact are atomic — a crash
between the two never happens, because there's only one transaction. Consumers get exactly-once
*effects* (not exactly-once delivery, which Kafka doesn't offer) for the cost of an extra table on
each side and a relay process to run, monitor and include in `docker compose`/K8s. The relay
introduces publish latency bounded by its poll interval rather than true real-time delivery, and
the outbox table needs its own retention/cleanup story once it grows.

## Revisit when
Publish latency from outbox polling becomes user-visible and needs to drop below the poll
interval (candidate fix: `LISTEN`/`NOTIFY` or CDC-triggered publishing instead of polling), or
outbox/inbox table growth needs an explicit archival policy.

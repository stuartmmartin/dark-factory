---
paths:
  - "services/*/src/*/interface/consumers/**"
  - "libs/py/sb_messaging/**"
  - "contracts/events/**"
---
# Kafka events
- Producers only write outbox rows; the relay publishes (A11). Consumers dedupe via the inbox
  and are idempotent: test duplicate delivery (T5).
- Every topic/version has a JSON Schema in `contracts/events/`; schema changes are additive
  within a version.

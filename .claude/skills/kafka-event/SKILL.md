---
name: kafka-event
description: Publish or consume a Kafka event — new domain event, topic, schema version, or consumer — via the transactional outbox and idempotent inbox in sb_messaging. Includes the JSON Schema contract and duplicate-delivery test.
---
# Kafka event
Reference: [messaging architecture](../../../docs/architecture/messaging.md). Rules: A11 (outbox),
A13 (tenancy), A14 (audit), C6 (bounded I/O), T5 (real infra).

**Publish**
1. Define the event in the service's `domain/events.py` as a `sb_kernel.events.DomainEvent`
   subclass: `event_type: ClassVar[str] = "<service>.<entity>.<past_tense>"`, a `schema_version`
   (default 1) and `event_key()`. The topic is `<event_type>.v<schema_version>`.
   Events for the same key are ordered, so pick the key that needs ordering (an account id, not
   a tenant id, unless tenant-wide order matters).
2. Write `contracts/events/<topic>.json`, the JSON Schema of the payload. Within a version,
   changes are additive only. A breaking change gets a new `schema_version`, so a new topic.
3. In the use case: `uow.outbox.add(Event(...))` before `await uow.commit()`. Never publish to Kafka
   directly. The unit of work is single use, so create a new one per use case.
4. The `OutboxRelay` (`sb_messaging.relay`) moves rows to Kafka. Run one loop calling
   `run_once()` per service. It is single-active via an advisory lock, so extra replicas are safe.
5. Tests: the use case unit test asserts the fake outbox received the event (T2). A contract
   test validates `event.model_dump(mode="json")` against the schema file.

**Consume**
1. Handler `async def handle_<event>(envelope: EventEnvelope, uow: <Service>UnitOfWork) -> None`
   in `interface/consumers/`. It parses `envelope.payload` into a pydantic model and calls exactly
   one use case (A8), passing it `sb_db.uow.joined(uow)` as its uow factory:
   `await UseCase(joined(uow), clock)(command)`. The use case then runs inside the inbox
   transaction: its `commit()` is a no-op and `process()` commits the business writes and the
   inbox row together. To abort, the use case raises (its `rollback()` is a no-op too). The use
   case must type its factory as `Callable[[], AbstractAsyncContextManager[<Service>UnitOfWork]]`
   to accept it. The unit of work already runs as the envelope's tenant and actor.
2. Wire it in `bootstrap.py`:
   `KafkaInboxConsumer(bootstrap, group_id, topics, consumer="<service>.<handler>", handler=...,
   uow_factory=..., tables=..., clock=...)`, then `await consumer.run(stop_event)`.
3. Decide the poison-message policy. The default re-raises (the supervisor restarts the consumer,
   which resumes at the failed message). Pass `on_poison` returning `"skip"` only for a message
   that can never decode. A dead-letter topic does not exist yet.
4. Integration test: deliver the same message twice and assert the effect happened once (T5).
   Also make the handler raise after the use case ran once, and assert that neither the
   business row nor the inbox row persisted, and that the redelivery applies it once.

Topics are created from `contracts/events/*.json` by kafka-init on `make up infra`.

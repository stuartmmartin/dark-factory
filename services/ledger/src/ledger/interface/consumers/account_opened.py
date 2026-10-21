"""`AccountOpened` → `RecordAccountOpened`: the reference consumer that future services copy.

The pattern (D13):
- `sb_messaging.inbox.process` calls `handle` inside its unit of work, after inserting the
  inbox row `(CONSUMER, event_id)`, and runs it as the event's tenant and actor (D11). The
  tenant and actor are trusted because only our services can produce to our topics (the
  Kafka trust boundary, docs/architecture/messaging.md).
- The handler parses the payload and calls exactly one use case (A8), passing it
  `sb_db.uow.joined(uow)` as its unit-of-work factory. The use case's `commit()` is then a
  no-op, and `process()` makes the one commit: the business writes, the audit event, any
  outbox rows and the inbox row commit together, or none of them do.
- To abort, raise. `rollback()` inside a joined view is a no-op too. The exception propagates
  out of `process()`, nothing persists (inbox row included), and the redelivery applies the
  effect exactly once. A duplicate delivery finds its inbox row and never reaches `handle`.
"""

from __future__ import annotations

from ledger.application.dto import RecordAccountOpenedCommand
from ledger.application.use_cases.record_account_opened import RecordAccountOpened
from ledger.domain.events import AccountOpened
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from sb_db.uow import joined
from sb_messaging.envelope import EventEnvelope

__all__ = ["CONSUMER", "TOPIC", "handle"]

CONSUMER = "ledger.account_opened"
TOPIC = AccountOpened.topic()


async def handle(envelope: EventEnvelope, uow: SqlLedgerUnitOfWork) -> None:
    event = AccountOpened.model_validate(envelope.payload)
    await RecordAccountOpened(joined(uow))(RecordAccountOpenedCommand(account_id=event.account_id))

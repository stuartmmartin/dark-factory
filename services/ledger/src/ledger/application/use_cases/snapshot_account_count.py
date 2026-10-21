"""Snapshot the tenant's account count for a date (called by the workflow activity).

Business rules:
    R1: It records the tenant's current account count as the snapshot for the date;
        re-running for the same date overwrites it (one snapshot per date).
    R2: It writes one audit event recording the date and the count.
    R3: A command carrying an idempotency key already used for the same request returns the
        stored result flagged `replayed` and writes nothing (no second audit event); the same
        key with a different request is IdempotencyKeyReused.

Temporal retries re-run activities, so the activity passes a deterministic key (D18).
"""

from __future__ import annotations

from ledger.application.dto import SnapshotAccountCountCommand, SnapshotResult, request_hash
from ledger.application.ports import UowFactory
from sb_kernel.errors import IdempotencyKeyReused


class SnapshotAccountCount:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def __call__(self, command: SnapshotAccountCountCommand) -> SnapshotResult:
        fingerprint = request_hash(command)
        async with self._uow() as uow:
            if command.idempotency_key is not None:  # R3: a retry replays and writes nothing
                stored = await uow.idempotency.get(command.idempotency_key)
                if stored is not None:
                    if stored.request_hash != fingerprint:
                        raise IdempotencyKeyReused(
                            "idempotency key already used for a different request"
                        )
                    return SnapshotResult.model_validate({**stored.response, "replayed": True})
            accounts = await uow.stats.count()  # R1: one snapshot per date, last run wins
            await uow.stats.upsert_snapshot(command.as_of, accounts)
            result = SnapshotResult(as_of=command.as_of, accounts=accounts)
            stored_body = result.model_dump(mode="json", exclude={"replayed"})
            uow.audit.record(  # R2
                action="account_count.snapshot",
                entity_type="account_count_snapshot",
                entity_id=command.as_of.isoformat(),
                before=None,
                after=stored_body,
            )
            if command.idempotency_key is not None:  # R3
                await uow.idempotency.save(command.idempotency_key, fingerprint, stored_body)
            await uow.commit()
            return result

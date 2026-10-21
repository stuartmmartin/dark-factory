"""Count an opened account in the tenant's projection (called by the AccountOpened consumer).

Business rules:
    R1: It increments the current tenant's account count by one and returns the new count.
    R2: It writes one audit event recording the account and the new count, in the same
        transaction as the count.
    R3: The account must exist in the tenant; an unknown account is NotFound and nothing is
        counted.

The consumer passes `sb_db.uow.joined(uow)` as `uow`, so `commit()` below is a no-op and the
inbox makes the one commit (D13). The use case aborts by raising, never by `rollback()`.
"""

from __future__ import annotations

from ledger.application.dto import AccountCountResult, RecordAccountOpenedCommand
from ledger.application.ports import UowFactory
from sb_kernel.errors import NotFound


class RecordAccountOpened:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def __call__(self, command: RecordAccountOpenedCommand) -> AccountCountResult:
        async with self._uow() as uow:
            if await uow.accounts.get(command.account_id) is None:  # R3
                raise NotFound(f"account {command.account_id} not found")
            accounts = await uow.stats.increment()  # R1
            uow.audit.record(  # R2: same transaction as the count
                action="account_count.increment",
                entity_type="account_count",
                entity_id=str(command.account_id),
                before=None,
                after={"accounts": accounts},
            )
            await uow.commit()
            return AccountCountResult(accounts=accounts)

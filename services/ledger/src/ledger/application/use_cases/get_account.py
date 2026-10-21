"""Read one account of the current tenant.

Business rules:
    R1: It returns the account of the current tenant.
    R2: An unknown account, or another tenant's, is NotFound (never Forbidden).

Read-only: no commit, audit or event. The unit of work rolls back on exit.
"""

from __future__ import annotations

from ledger.application.dto import AccountResult, GetAccountQuery, to_result
from ledger.application.ports import UowFactory
from sb_kernel.errors import NotFound


class GetAccount:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def __call__(self, query: GetAccountQuery) -> AccountResult:
        async with self._uow() as uow:
            account = await uow.accounts.get(query.account_id)  # R1
            if account is None:  # R2: RLS hides another tenant's row, so it reads as unknown
                raise NotFound(f"account {query.account_id} not found")
            return to_result(account)

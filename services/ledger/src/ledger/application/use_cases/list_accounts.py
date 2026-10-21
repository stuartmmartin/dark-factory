"""List the current tenant's accounts.

Business rules:
    R1: It returns only the current tenant's accounts, oldest first (opened_at, then id).
    R2: It returns at most `limit` accounts; a limit outside 1-200 is ValidationFailed.

Read-only: no commit, audit or event. The unit of work rolls back on exit.
"""

from __future__ import annotations

from ledger.application.dto import AccountListResult, ListAccountsQuery, to_result
from ledger.application.ports import UowFactory
from sb_kernel.errors import ValidationFailed

MAX_LIMIT = 200


class ListAccounts:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def __call__(self, query: ListAccountsQuery) -> AccountListResult:
        if not 1 <= query.limit <= MAX_LIMIT:  # R2
            raise ValidationFailed(f"limit must be 1-{MAX_LIMIT}")
        async with self._uow() as uow:
            accounts = await uow.accounts.oldest_first(query.limit)  # R1: RLS scopes the tenant
            return AccountListResult(items=tuple(to_result(a) for a in accounts))

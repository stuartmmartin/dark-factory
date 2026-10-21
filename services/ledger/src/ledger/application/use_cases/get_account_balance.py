"""Read an account's debits, credits and balance, for the current tenant.

Business rules:
    R1: It returns the sums of the account's debit and credit lines and the balance
        (double_entry P3: debits - credits) in the account's currency; with no lines, all zero.
    R2: An unknown account, or another tenant's, is NotFound (never Forbidden).

Read-only: no commit, audit or event. The unit of work rolls back on exit.
"""

from __future__ import annotations

from ledger.application.dto import BalanceResult, GetAccountBalanceQuery
from ledger.application.policies.double_entry import account_balance
from ledger.application.ports import UowFactory
from ledger.domain.amounts import to_decimal_str
from sb_kernel.errors import NotFound


class GetAccountBalance:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def __call__(self, query: GetAccountBalanceQuery) -> BalanceResult:
        async with self._uow() as uow:
            account = await uow.accounts.get(query.account_id)
            if account is None:  # R2: RLS hides another tenant's row, so it reads as unknown
                raise NotFound(f"account {query.account_id} not found")
            totals = await uow.journal.totals(account)  # R1
            return BalanceResult(
                account_id=account.id,
                currency=account.currency.code,
                debits=to_decimal_str(totals.debits),
                credits=to_decimal_str(totals.credits),
                balance=to_decimal_str(account_balance(totals.debits, totals.credits)),
            )

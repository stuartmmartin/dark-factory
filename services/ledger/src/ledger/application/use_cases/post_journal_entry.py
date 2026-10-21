"""Post a balanced journal entry between accounts of the current tenant.

Business rules:
    R1: The entry has 2-100 lines, each amount positive and within its currency's minor units,
        debits equal to credits (double_entry P1, P2), and a description of 1-200 non-blank
        characters; otherwise ValidationFailed and nothing is written.
    R2: Every line's account must belong to the current tenant; an unknown account, or another
        tenant's, is NotFound and nothing is written.
    R3: Every line's account has the same currency, which becomes the entry's currency;
        otherwise CurrencyMismatch (422) and nothing is written.
    R4: Posting writes the entry with its lines and one audit event in the same transaction. The
        audit holds the amounts but not the description (free text in an append-only chain).
    R5: Idempotency follows OpenAccount R3: the same key and request after the first committed
        replays the original result flagged `replayed`, writing nothing; the same key with a
        different request is IdempotencyKeyReused (422); a racing duplicate is a Conflict (409).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from ledger.application.dto import (
    JournalEntryResult,
    JournalLineResult,
    PostJournalEntryCommand,
    request_hash,
)
from ledger.application.policies.double_entry import check_balanced, check_line_count
from ledger.application.ports import LedgerUnitOfWork, UowFactory
from ledger.domain.accounts import Account
from ledger.domain.amounts import to_decimal_str
from ledger.domain.journal import JournalEntry, JournalLine
from sb_kernel.clock import Clock
from sb_kernel.context import current_context
from sb_kernel.errors import CurrencyMismatch, IdempotencyKeyReused, NotFound
from sb_kernel.ids import new_id as default_new_id
from sb_kernel.money import Money


class PostJournalEntry:
    def __init__(
        self, uow: UowFactory, clock: Clock, new_id: Callable[[], UUID] = default_new_id
    ) -> None:
        self._uow, self._clock, self._new_id = uow, clock, new_id

    async def __call__(self, command: PostJournalEntryCommand) -> JournalEntryResult:
        fingerprint = request_hash(command)
        check_line_count(len(command.lines))  # R1: bounded before any per-line lookup
        async with self._uow() as uow:
            if command.idempotency_key is not None:  # R5: a sequential replay writes nothing
                stored = await uow.idempotency.get(command.idempotency_key)
                if stored is not None:
                    if stored.request_hash != fingerprint:
                        raise IdempotencyKeyReused(
                            "idempotency key already used for a different request"
                        )
                    return JournalEntryResult.model_validate({**stored.response, "replayed": True})
            accounts = await _load_accounts(uow, command)  # R2
            currencies = {account.currency for account in accounts}
            if len(currencies) > 1:  # R3
                codes = ", ".join(sorted(c.code for c in currencies))
                raise CurrencyMismatch(f"an entry's accounts must share one currency, got {codes}")
            (currency,) = currencies
            lines = tuple(
                JournalLine(line.account_id, line.side, Money.of(line.amount, currency))
                for line in command.lines
            )
            check_balanced(lines, currency)  # R1: double_entry P1 and P2
            entry = JournalEntry(  # R1: the entity validates the description
                id=self._new_id(),
                tenant_id=current_context().tenant_id,
                description=command.description,
                currency=currency,
                posted_at=self._clock.now(),
                lines=lines,
            )
            await uow.journal.add(entry)  # R4: entry, lines and audit in one transaction
            result = _to_result(entry)
            uow.audit.record(  # no description: free text never enters the append-only chain
                action="journal_entry.post",
                entity_type="journal_entry",
                entity_id=str(entry.id),
                before=None,
                after={
                    "id": entry.id,
                    "currency": currency.code,
                    "posted_at": entry.posted_at,
                    "lines": [line.model_dump(mode="json") for line in result.lines],
                },
            )
            if command.idempotency_key is not None:  # R5: a racing duplicate raises Conflict here
                stored_body = result.model_dump(mode="json", exclude={"replayed"})
                await uow.idempotency.save(command.idempotency_key, fingerprint, stored_body)
            await uow.commit()
            return result


async def _load_accounts(uow: LedgerUnitOfWork, command: PostJournalEntryCommand) -> list[Account]:
    """Each distinct account once, in line order; at most 100 lookups (R1 bounds the lines)."""
    accounts: list[Account] = []
    for account_id in dict.fromkeys(line.account_id for line in command.lines):
        account = await uow.accounts.get(account_id)
        if account is None:  # RLS hides another tenant's account, so it reads as unknown
            raise NotFound(f"account {account_id} not found")
        accounts.append(account)
    return accounts


def _to_result(entry: JournalEntry) -> JournalEntryResult:
    return JournalEntryResult(
        id=entry.id,
        description=entry.description,
        currency=entry.currency.code,
        posted_at=entry.posted_at,
        lines=tuple(
            JournalLineResult(
                account_id=line.account_id, side=line.side, amount=to_decimal_str(line.amount)
            )
            for line in entry.lines
        ),
    )

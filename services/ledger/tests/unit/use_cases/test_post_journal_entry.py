"""PostJournalEntry's rules: one `test_R<n>_*` per `R<n>` line of its docstring (T2)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from ledger.application.dto import JournalLineCommand, PostJournalEntryCommand, request_hash
from ledger.application.use_cases.post_journal_entry import PostJournalEntry
from ledger.domain.accounts import Account
from ledger.domain.journal import Side
from sb_kernel.clock import FixedClock
from sb_kernel.context import current_context
from sb_kernel.errors import (
    Conflict,
    CurrencyMismatch,
    IdempotencyKeyReused,
    NotFound,
    ValidationFailed,
)
from sb_kernel.money import Currency, Money
from sb_kernel.uow import StoredResponse

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
ENTRY_ID = UUID(int=0xE1)
CASH, EQUITY, EUROS, ELSEWHERE = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)


@pytest.fixture(autouse=True)
def accounts(state) -> None:
    def add(account_id: UUID, currency: str, tenant: UUID | None = None) -> None:
        state.accounts[account_id] = Account(
            id=account_id,
            tenant_id=tenant or current_context().tenant_id,
            name=f"Account {account_id.int}",
            currency=Currency.of(currency),
            opened_at=CLOCK.now(),
        )

    add(CASH, "USD")
    add(EQUITY, "USD")
    add(EUROS, "EUR")
    add(ELSEWHERE, "USD", tenant=UUID(int=0xBEEF))


def line(account: UUID, side: Side, amount: str) -> JournalLineCommand:
    return JournalLineCommand(account_id=account, side=side, amount=amount)


def cmd(
    *lines: JournalLineCommand, description: str = "Owner contribution", key: str | None = None
) -> PostJournalEntryCommand:
    lines = lines or (line(CASH, Side.DEBIT, "100.00"), line(EQUITY, Side.CREDIT, "100.00"))
    return PostJournalEntryCommand(description=description, lines=lines, idempotency_key=key)


def post(uow) -> PostJournalEntry:
    return PostJournalEntry(uow, CLOCK, new_id=lambda: ENTRY_ID)


def assert_nothing_written(state) -> None:
    assert state.commits == 0
    assert not state.entries
    assert not state.audit


@pytest.mark.parametrize(
    "command",
    [
        cmd(line(CASH, Side.DEBIT, "100.00")),
        cmd(line(CASH, Side.DEBIT, "100.00"), line(EQUITY, Side.CREDIT, "99.99")),
        cmd(line(CASH, Side.DEBIT, "0"), line(EQUITY, Side.CREDIT, "0")),
        cmd(line(CASH, Side.DEBIT, "1.005"), line(EQUITY, Side.CREDIT, "1.005")),
        cmd(description="   "),
        cmd(description="x" * 201),
    ],
    ids=["one-line", "unbalanced", "zero", "excess-precision", "blank-description", "201-chars"],
)
async def test_R1_invalid_entries_are_rejected_and_nothing_is_written(uow, state, command) -> None:
    with pytest.raises(ValidationFailed):
        await post(uow)(command)
    assert_nothing_written(state)


async def test_R1_more_than_100_lines_is_rejected_before_any_account_is_loaded(uow, state) -> None:
    unknown = [line(UUID(int=1000 + i), Side.DEBIT, "1.00") for i in range(101)]
    with pytest.raises(ValidationFailed, match="lines"):  # not NotFound: the bound comes first
        await post(uow)(cmd(*unknown))
    assert_nothing_written(state)


@pytest.mark.parametrize("missing", [UUID(int=0xDEAD), ELSEWHERE], ids=["unknown", "other-tenant"])
async def test_R2_an_account_outside_the_tenant_is_not_found(uow, state, missing) -> None:
    with pytest.raises(NotFound):
        await post(uow)(cmd(line(CASH, Side.DEBIT, "5.00"), line(missing, Side.CREDIT, "5.00")))
    assert_nothing_written(state)


async def test_R3_accounts_in_different_currencies_are_a_currency_mismatch(uow, state) -> None:
    with pytest.raises(CurrencyMismatch):
        await post(uow)(cmd(line(CASH, Side.DEBIT, "5.00"), line(EUROS, Side.CREDIT, "5.00")))
    assert_nothing_written(state)


async def test_R3_the_entry_takes_its_accounts_currency(uow, state) -> None:
    result = await post(uow)(cmd())
    assert result.currency == "USD"
    assert state.entries[ENTRY_ID].currency == Currency.of("USD")


async def test_R4_entry_lines_and_audit_are_written_together(uow, state) -> None:
    result = await post(uow)(
        cmd(
            line(CASH, Side.DEBIT, "60.00"),
            line(CASH, Side.DEBIT, "40"),
            line(EQUITY, Side.CREDIT, "100.00"),
        )
    )
    assert state.commits == 1
    entry = state.entries[ENTRY_ID]
    assert [(ln.account_id, ln.side, ln.amount) for ln in entry.lines] == [
        (CASH, Side.DEBIT, Money.of("60.00", "USD")),
        (CASH, Side.DEBIT, Money.of("40", "USD")),
        (EQUITY, Side.CREDIT, Money.of("100.00", "USD")),
    ]
    assert result.id == ENTRY_ID
    assert result.posted_at == CLOCK.now()
    assert [(ln.side, ln.amount) for ln in result.lines] == [
        (Side.DEBIT, "60.00"),
        (Side.DEBIT, "40.00"),
        (Side.CREDIT, "100.00"),
    ]
    assert not result.replayed
    assert [(a.action, a.entity_id) for a in state.audit] == [("journal_entry.post", str(ENTRY_ID))]
    after = state.audit[0].after
    assert after["currency"] == "USD"
    assert after["lines"][0] == {"account_id": str(CASH), "side": "debit", "amount": "60.00"}
    assert "description" not in after


async def test_R5_same_key_same_request_replays_without_writing(uow, state) -> None:
    first = await post(uow)(cmd(key="k-1"))
    second = await post(uow)(cmd(key="k-1"))
    assert second == first.model_copy(update={"replayed": True})
    assert len(state.entries) == 1
    assert len(state.audit) == 1
    assert state.commits == 1


async def test_R5_same_key_different_request_is_idempotency_key_reused(uow, state) -> None:
    await post(uow)(cmd(key="k-2"))
    with pytest.raises(IdempotencyKeyReused):
        await post(uow)(cmd(description="Something else", key="k-2"))
    assert len(state.entries) == 1


async def test_R5_racing_duplicate_is_conflict_and_writes_nothing(uow, state) -> None:
    command = cmd(key="k-3")
    state.idempotency[(current_context().tenant_id, "k-3")] = StoredResponse(
        request_hash(command), {}
    )
    state.hide_idempotency_reads = True
    with pytest.raises(Conflict):
        await post(uow)(command)
    assert_nothing_written(state)

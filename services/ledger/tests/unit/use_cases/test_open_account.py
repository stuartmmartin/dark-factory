from datetime import UTC, datetime

import pytest

from ledger.application.dto import OpenAccountCommand, request_hash
from ledger.application.use_cases.open_account import OpenAccount
from ledger.domain.events import AccountOpened
from sb_kernel.clock import FixedClock
from sb_kernel.context import current_context
from sb_kernel.errors import Conflict, IdempotencyKeyReused, ValidationFailed
from sb_kernel.uow import StoredResponse

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))


def cmd(
    name: str = "Operating cash", currency: str = "USD", key: str | None = None
) -> OpenAccountCommand:
    return OpenAccountCommand(name=name, currency=currency, idempotency_key=key)


@pytest.mark.parametrize(
    "command",
    [cmd(currency="XYZ"), cmd(name="   "), cmd(name="x" * 201)],
    ids=["currency", "blank-name", "201-char-name"],
)
async def test_R1_invalid_input_is_rejected_and_nothing_is_written(uow, state, command) -> None:
    with pytest.raises(ValidationFailed):
        await OpenAccount(uow, CLOCK)(command)
    assert state.commits == 0
    assert not state.accounts
    assert not state.events


async def test_R2_account_audit_and_event_are_written_together(uow, state) -> None:
    result = await OpenAccount(uow, CLOCK)(cmd())
    assert state.commits == 1
    assert list(state.accounts) == [result.id]
    assert result.opened_at == CLOCK.now()
    assert result.currency == "USD"
    assert not result.replayed
    assert state.events == [AccountOpened(account_id=result.id, currency="USD")]
    assert [(a.action, a.entity_id) for a in state.audit] == [("account.open", str(result.id))]
    # No free-text PII in the append-only audit chain (controller ruling): no account name.
    assert state.audit[0].after == {
        "id": str(result.id),
        "currency": "USD",
        "opened_at": "2026-03-01T12:00:00+00:00",
    }
    assert "name" not in state.audit[0].after


async def test_R3_same_key_same_request_replays_without_writing(uow, state) -> None:
    open_ = OpenAccount(uow, CLOCK)
    first = await open_(cmd(key="k-1"))
    second = await open_(cmd(key="k-1"))
    assert second == first.model_copy(update={"replayed": True})
    assert len(state.accounts) == 1
    assert len(state.audit) == 1
    assert state.commits == 1


async def test_R3_same_key_different_request_is_idempotency_key_reused(uow, state) -> None:
    open_ = OpenAccount(uow, CLOCK)
    await open_(cmd(key="k-2"))
    with pytest.raises(IdempotencyKeyReused, match="idempotency"):  # 422, not 409 (D15)
        await open_(cmd(name="Other", key="k-2"))
    assert len(state.accounts) == 1


async def test_R3_racing_duplicate_is_conflict_and_writes_nothing(uow, state) -> None:
    command = cmd(key="k-3")
    # The first request committed while this one was between its read and its save.
    state.idempotency[(current_context().tenant_id, "k-3")] = StoredResponse(
        request_hash(command), {}
    )
    state.hide_idempotency_reads = True
    with pytest.raises(Conflict):
        await OpenAccount(uow, CLOCK)(command)
    assert state.commits == 0
    assert not state.accounts

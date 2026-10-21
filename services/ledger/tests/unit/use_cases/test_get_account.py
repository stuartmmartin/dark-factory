from datetime import UTC, datetime
from uuid import UUID

import pytest

from ledger.application.dto import GetAccountQuery, OpenAccountCommand
from ledger.application.use_cases.get_account import GetAccount
from ledger.application.use_cases.open_account import OpenAccount
from sb_kernel.clock import FixedClock
from sb_kernel.context import RequestContext, use_context
from sb_kernel.errors import NotFound

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))


async def test_R1_returns_the_current_tenants_account(uow) -> None:
    opened = await OpenAccount(uow, CLOCK)(
        OpenAccountCommand(name="Operating cash", currency="EUR")
    )
    found = await GetAccount(uow)(GetAccountQuery(account_id=opened.id))
    assert found == opened
    assert not found.replayed


async def test_R2_unknown_account_is_not_found(uow) -> None:
    with pytest.raises(NotFound):
        await GetAccount(uow)(GetAccountQuery(account_id=UUID(int=404)))


async def test_R2_another_tenants_account_is_not_found_not_forbidden(uow) -> None:
    other = RequestContext(tenant_id=UUID(int=2), actor="other", request_id="req-2")
    with use_context(other):
        theirs = await OpenAccount(uow, CLOCK)(OpenAccountCommand(name="Theirs", currency="USD"))
    with pytest.raises(NotFound):
        await GetAccount(uow)(GetAccountQuery(account_id=theirs.id))

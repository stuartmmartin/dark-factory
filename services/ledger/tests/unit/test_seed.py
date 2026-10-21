from datetime import UTC, datetime
from uuid import UUID

from ledger_fakes import LedgerState  # type: ignore[import-not-found]

from ledger.application.ports import UowFactory
from ledger.application.use_cases.open_account import OpenAccount
from ledger.seed import DEMO_TENANT, SEED_ACCOUNT_NAME, parse_args, seed
from sb_kernel.clock import FixedClock
from sb_kernel.context import current_context

CLOCK = FixedClock(datetime(2026, 3, 1, 12, tzinfo=UTC))
OTHER_TENANT = UUID(int=0xBEEF)


def test_demo_tenant_is_the_documented_fixed_uuid() -> None:
    assert str(DEMO_TENANT) == "00000000-0000-0000-0000-0000000000d3"
    assert parse_args([]).tenant == DEMO_TENANT
    assert parse_args(["--tenant", str(OTHER_TENANT)]).tenant == OTHER_TENANT


async def test_seed_opens_operating_cash_under_the_given_tenant(
    uow: UowFactory, state: LedgerState
) -> None:
    caller = current_context()
    result = await seed(OpenAccount(uow, CLOCK), DEMO_TENANT)
    assert (result.name, result.currency, result.replayed) == (SEED_ACCOUNT_NAME, "USD", False)
    assert [a.tenant_id for a in state.accounts.values()] == [DEMO_TENANT]
    assert current_context() == caller  # the seed's context does not leak


async def test_rerunning_the_seed_replays_instead_of_opening_a_second_account(
    uow: UowFactory, state: LedgerState
) -> None:
    open_account = OpenAccount(uow, CLOCK)
    first = await seed(open_account, DEMO_TENANT)
    again = await seed(open_account, DEMO_TENANT)
    assert again.id == first.id
    assert again.replayed
    assert list(state.accounts) == [first.id]

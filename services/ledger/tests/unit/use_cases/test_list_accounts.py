"""ListAccounts' rules: one `test_R<n>_*` per `R<n>` line of its docstring (T2)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from ledger.application.dto import ListAccountsQuery
from ledger.application.use_cases.list_accounts import ListAccounts
from ledger.domain.accounts import Account
from sb_kernel.context import current_context
from sb_kernel.errors import ValidationFailed
from sb_kernel.money import Currency

AT = datetime(2026, 3, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def accounts(state) -> None:
    tenant = current_context().tenant_id
    # Opened in reverse id order, so "oldest first" differs from insertion and id order.
    for n, name in enumerate(["Third", "Second", "First"]):
        state.accounts[UUID(int=n + 1)] = Account(
            id=UUID(int=n + 1),
            tenant_id=tenant,
            name=name,
            currency=Currency.of("USD"),
            opened_at=AT - timedelta(days=n),
        )
    state.accounts[UUID(int=99)] = Account(
        id=UUID(int=99),
        tenant_id=UUID(int=0xBEEF),
        name="Someone else's",
        currency=Currency.of("USD"),
        opened_at=AT - timedelta(days=30),
    )


async def test_R1_returns_only_the_tenants_accounts_oldest_first(uow) -> None:
    result = await ListAccounts(uow)(ListAccountsQuery())
    assert [a.name for a in result.items] == ["First", "Second", "Third"]


async def test_R2_returns_at_most_limit_accounts(uow) -> None:
    result = await ListAccounts(uow)(ListAccountsQuery(limit=2))
    assert [a.name for a in result.items] == ["First", "Second"]


@pytest.mark.parametrize("limit", [0, 201])
async def test_R2_a_limit_outside_1_to_200_is_rejected(uow, limit: int) -> None:
    with pytest.raises(ValidationFailed, match="limit"):
        await ListAccounts(uow)(ListAccountsQuery(limit=limit))

from collections.abc import Iterator
from uuid import UUID

import pytest
from ledger_fakes import LedgerState, fake_factory  # type: ignore[import-not-found]

from ledger.application.ports import UowFactory
from sb_kernel.context import RequestContext, use_context

TENANT = UUID(int=0xF00D)


@pytest.fixture
def state() -> LedgerState:
    return LedgerState()


@pytest.fixture
def uow(state: LedgerState) -> UowFactory:
    # A new single-use unit of work per call, sharing committed state (D14).
    return fake_factory(state)


@pytest.fixture(autouse=True)
def tenant_context() -> Iterator[RequestContext]:
    ctx = RequestContext(tenant_id=TENANT, actor="tester", request_id="req-1")
    with use_context(ctx):
        yield ctx

from uuid import uuid4

import pytest

from sb_kernel.context import RequestContext, current_context, optional_context, use_context
from sb_kernel.errors import Forbidden


def test_no_context_raises_forbidden() -> None:
    assert optional_context() is None
    with pytest.raises(Forbidden, match="no request context"):
        current_context()


def test_use_context_sets_and_restores() -> None:
    ctx = RequestContext(tenant_id=uuid4(), actor="alice", request_id="r1")
    with use_context(ctx):
        assert current_context() is ctx
    assert optional_context() is None


def test_use_context_nests_and_resets_after_exception() -> None:
    outer = RequestContext(tenant_id=uuid4(), actor="a", request_id="1")
    inner = RequestContext(tenant_id=uuid4(), actor="b", request_id="2")

    def fail_inside_inner() -> None:
        with use_context(inner):
            assert current_context() is inner
            raise RuntimeError("boom")

    with use_context(outer):
        with pytest.raises(RuntimeError):
            fail_inside_inner()
        assert current_context() is outer
    assert optional_context() is None

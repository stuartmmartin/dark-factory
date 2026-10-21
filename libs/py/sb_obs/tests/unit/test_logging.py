import io
import json
import logging
from uuid import uuid4

import pytest

from sb_kernel.context import RequestContext, use_context
from sb_obs.logging import configure_logging, get_logger
from sb_obs.redaction import REDACTED


def test_json_logs_carry_context_and_redact() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", json=True, stream=stream)
    tenant = uuid4()
    with use_context(RequestContext(tenant_id=tenant, actor="alice", request_id="r1")):
        get_logger("ledger.test").info("ledger.entry_posted", password="hunter2", amount="1.00")  # noqa: S106 - fake secret
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "ledger.entry_posted"
    assert record["tenant_id"] == str(tenant)
    assert record["request_id"] == "r1"
    assert record["password"] == REDACTED
    assert record["amount"] == "1.00"
    assert record["level"] == "info"


def test_logs_without_context_have_no_tenant() -> None:
    stream = io.StringIO()
    configure_logging(json=True, stream=stream)
    get_logger("x").info("x.happened")
    assert "tenant_id" not in json.loads(stream.getvalue().strip().splitlines()[-1])


def test_exception_traceback_is_rendered_and_scrubbed() -> None:
    stream = io.StringIO()
    configure_logging(json=True, stream=stream)
    try:
        raise RuntimeError("upstream said Bearer abc.def")
    except RuntimeError:
        get_logger("x").exception("x.failed")
    out = stream.getvalue()
    assert "Traceback" in out
    assert "RuntimeError" in out
    assert "abc.def" not in out


def test_level_is_case_insensitive_and_validated() -> None:
    stream = io.StringIO()
    configure_logging(level="debug", stream=stream)
    get_logger("x").debug("x.debugged")
    assert "x.debugged" in stream.getvalue()
    with pytest.raises(ValueError, match="log level"):
        configure_logging(level="LOUD")


@pytest.mark.parametrize("name", ["sqlalchemy.engine", "uvicorn.error", "temporalio.worker"])
def test_stdlib_library_logs_are_rendered_as_json_and_redacted(name: str) -> None:
    stream = io.StringIO()
    configure_logging(json=True, stream=stream)
    tenant = uuid4()
    with use_context(RequestContext(tenant_id=tenant, actor="alice", request_id="r1")):
        logging.getLogger(name).warning("connecting to %s", "postgresql://u:hunter2@db/x")
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["logger"] == name
    assert record["level"] == "warning"
    assert record["tenant_id"] == str(tenant)
    assert "hunter2" not in stream.getvalue()


def test_reconfiguring_does_not_duplicate_the_stdlib_handler() -> None:
    stream = io.StringIO()
    configure_logging(json=True, stream=io.StringIO())
    configure_logging(json=True, stream=stream)
    logging.getLogger("sqlalchemy").warning("once")
    assert len(stream.getvalue().strip().splitlines()) == 1

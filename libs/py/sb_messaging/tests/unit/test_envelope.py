from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sb_messaging.envelope import EventEnvelope


def _envelope(**over: object) -> EventEnvelope:
    data: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": "ledger.journal_entry.posted",
        "schema_version": 1,
        "topic": "ledger.journal_entry.posted.v1",
        "key": "k",
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
        "tenant_id": uuid4(),
        "actor": "alice",
        "request_id": "r1",
        "trace_id": None,
        "payload": {"amount": "1.00"},
    }
    data.update(over)
    return EventEnvelope.model_validate(data)


def test_round_trips_through_bytes() -> None:
    env = _envelope()
    assert EventEnvelope.from_bytes(env.to_bytes()) == env


def test_context_carries_tenant_and_actor() -> None:
    env = _envelope()
    ctx = env.context()
    assert (ctx.tenant_id, ctx.actor, ctx.request_id) == (env.tenant_id, "alice", "r1")


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _envelope(occurred_at=datetime(2026, 1, 1))  # noqa: DTZ001 - asserting rejection


def test_missing_tenant_is_rejected() -> None:
    data = _envelope().model_dump()
    del data["tenant_id"]
    with pytest.raises(ValidationError, match="tenant_id"):
        EventEnvelope.model_validate(data)


def test_malformed_tenant_is_rejected() -> None:
    with pytest.raises(ValidationError, match="tenant_id"):
        _envelope(tenant_id="not-a-uuid")


def test_unknown_top_level_fields_are_ignored() -> None:
    """Tolerant reader: an envelope from a newer producer still decodes (and drops the extra)."""
    env = _envelope()
    newer = env.to_bytes().replace(b"{", b'{"added_later":"x",', 1)
    decoded = EventEnvelope.from_bytes(newer)
    assert decoded == env
    assert "added_later" not in decoded.model_dump()


def test_topic_must_match_event_type_and_version() -> None:
    with pytest.raises(ValidationError, match="topic"):
        _envelope(topic="ledger.journal_entry.posted.v2")


@pytest.mark.parametrize("actor", ["", "a" * 129, "alice bob", "alice\nlevel=error", "ali;ce", "é"])
def test_actor_outside_the_http_charset_and_length_is_rejected(actor: str) -> None:
    with pytest.raises(ValidationError, match="actor"):
        _envelope(actor=actor)


@pytest.mark.parametrize("request_id", ["", "r" * 129, "r 1", "r1\n", "r@1", "r/1"])
def test_request_id_outside_the_http_charset_and_length_is_rejected(request_id: str) -> None:
    with pytest.raises(ValidationError, match="request_id"):
        _envelope(request_id=request_id)


def test_actor_and_request_id_accept_what_http_accepts() -> None:
    env = _envelope(actor="svc:ledger@example.com", request_id="req-1.a:b_c")
    assert (env.actor, env.request_id) == ("svc:ledger@example.com", "req-1.a:b_c")
    assert _envelope(actor="a" * 128, request_id="r" * 128).actor == "a" * 128


def test_invalid_actor_on_the_wire_is_undecodable() -> None:
    raw = _envelope().to_bytes().replace(b'"actor":"alice"', b'"actor":"alice\\nforged"')
    with pytest.raises(ValidationError, match="actor"):
        EventEnvelope.from_bytes(raw)

import io
from collections import deque
from dataclasses import dataclass
from typing import Annotated

import pytest
from pydantic import BaseModel, SecretStr

from sb_obs.logging import configure_logging, get_logger
from sb_obs.redaction import (
    PII,
    REDACTED,
    redact_model,
    redact_processor,
    redact_string,
    redact_value,
)


class Client(BaseModel):
    name: Annotated[str, PII]
    tax_id: str
    city: str
    api_secret: SecretStr


def test_sensitive_keys_are_redacted_case_insensitively() -> None:
    assert redact_value("Password", "x") == REDACTED
    assert redact_value("client_tax_id", "123") == REDACTED
    assert redact_value("city", "Boston") == "Boston"


def test_secretstr_is_always_redacted() -> None:
    assert redact_value("anything", SecretStr("s")) == REDACTED


def test_model_redacts_pii_annotations_sensitive_names_and_secrets() -> None:
    model = Client(name="Ada", tax_id="123", city="Boston", api_secret=SecretStr("s"))
    assert redact_model(model) == {
        "name": REDACTED,
        "tax_id": REDACTED,
        "city": "Boston",
        "api_secret": REDACTED,
    }


def test_processor_redacts_nested_structures_and_models() -> None:
    model = Client(name="Ada", tax_id="1", city="X", api_secret=SecretStr("s"))
    event = {"event": "x.y", "headers": {"Authorization": "Bearer t"}, "client": model}
    out = redact_processor(None, "info", event)
    assert out["headers"] == {"Authorization": REDACTED}
    assert out["client"]["name"] == REDACTED
    assert out["event"] == "x.y"


# --- fix round 1 -------------------------------------------------------------------------


def _render(**fields: object) -> str:
    """Log through the real pipeline and return the raw rendered output."""
    stream = io.StringIO()
    configure_logging(json=True, stream=stream)
    event = fields.pop("event", "x.happened")
    get_logger("t").info(str(event), **fields)
    return stream.getvalue()


@pytest.mark.parametrize(
    "key",
    [
        "x-api-key",
        "X-API-KEY",
        "Set-Cookie",
        "private_key",
        "db_passwd",
        "PWD",
        "Proxy-Authorization",
        "card_number",
        "cvv",
        "session_id",
        "jwt",
        "refresh_token",
        "credentials",
        "bearer",
    ],
)
def test_extended_and_hyphenated_keys_are_redacted(key: str) -> None:
    out = _render(**{key: "SUPERSECRET123"})
    assert "SUPERSECRET123" not in out
    assert REDACTED in out


def test_innocent_keys_are_not_redacted() -> None:
    out = _render(pin_count="7", dob_year="1990", city="Boston")
    assert '"pin_count": "7"' in out
    assert "Boston" in out


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer abc123.def456",
        "postgres://user:hunter2pw@db.internal:5432/x",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        "sk-abcdefghijklmnop1234",
    ],
)
def test_secret_shaped_string_values_are_scrubbed(secret: str) -> None:
    out = _render(detail=f"got {secret} here", event=f"msg {secret}")
    for needle in ("abc123.def456", "hunter2pw", "eyJhbGci", "sk-abcdefghijklmnop1234"):
        assert needle not in out
    assert REDACTED in out


def test_redact_string_leaves_plain_text() -> None:
    assert redact_string("ledger posted 3 entries") == "ledger posted 3 entries"


@dataclass
class Holder:
    label: str
    password: str


def test_traversal_covers_sets_deques_dataclasses() -> None:
    out = _render(
        a={"tok": {"x"}},
        b=deque(["Bearer zzz.yyy"]),
        c=Holder(label="ok", password="DCPASS"),  # noqa: S106 - fake secret
        d=frozenset({"Bearer qqq.rrr"}),
        e=("Bearer ttt.uuu",),
    )
    for needle in ("zzz.yyy", "DCPASS", "qqq.rrr", "ttt.uuu"):
        assert needle not in out
    assert '"label": "ok"' in out


def test_self_referential_dict_does_not_raise() -> None:
    loop: dict[str, object] = {"name": "n"}
    loop["self"] = loop
    out = _render(payload=loop)
    assert "[CYCLE]" in out


def test_depth_is_limited() -> None:
    deep: object = "Bearer deepsecret.tok"
    for _ in range(30):
        deep = {"k": deep}
    out = _render(payload=deep)
    assert "deepsecret" not in out


def test_unknown_objects_and_exceptions_are_repr_scrubbed() -> None:
    class Thing:
        def __repr__(self) -> str:
            return "Thing(Bearer objsecret.tok)"

    out = _render(thing=Thing(), err=ValueError("Bearer excsecret.tok"))
    assert "objsecret" not in out
    assert "excsecret" not in out


class PiiHolder(BaseModel):
    maybe: Annotated[str, PII] | None = None
    many: list[Annotated[str, PII]] = []
    mapping: dict[str, Annotated[str, PII]] = {}
    plain: str = "fine"


def test_pii_found_through_optional_and_containers() -> None:
    model = PiiHolder(maybe="Ada", many=["Bob"], mapping={"k": "Cy"}, plain="fine")
    dumped = repr(redact_model(model))
    for needle in ("Ada", "Bob", "Cy"):
        assert needle not in dumped
    assert "fine" in dumped

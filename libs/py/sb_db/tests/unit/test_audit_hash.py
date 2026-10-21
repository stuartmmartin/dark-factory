from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from sb_db.audit import canonical_json, chain_hash


def test_canonical_json_is_order_independent_and_handles_decimal_uuid() -> None:
    a = canonical_json({"b": Decimal("1.10"), "a": UUID(int=1)})
    b = canonical_json({"a": UUID(int=1), "b": Decimal("1.10")})
    assert a == b == '{"a":"00000000-0000-0000-0000-000000000001","b":"1.10"}'


def test_canonical_json_normalizes_datetimes_to_utc() -> None:
    utc = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    shifted = utc.astimezone(timezone(timedelta(hours=5)))
    assert canonical_json({"at": utc}) == canonical_json({"at": shifted})
    assert canonical_json({"at": shifted}) == '{"at":"2026-01-01T09:00:00+00:00"}'


def test_chain_hash_depends_on_previous_hash() -> None:
    row = {"action": "x"}
    assert chain_hash(None, row) != chain_hash("abc", row)
    assert len(chain_hash(None, row)) == 64


@pytest.mark.parametrize("payload", [{"x": 1.5}, {"x": [{"y": 0.1}]}, [2.0]])
def test_canonical_json_rejects_floats(payload: object) -> None:
    with pytest.raises(TypeError, match="float"):
        canonical_json(payload)

from uuid import UUID

import pytest

from sb_workflows.ids import workflow_id

U1 = UUID(int=1)
U2 = UUID(int=2)


def test_deterministic_id() -> None:
    assert workflow_id("eod-snapshot", U1, "2026-01-01") == (
        "eod-snapshot-00000000-0000-0000-0000-000000000001-2026-01-01"
    )


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("", "k"),
        ("n", ""),
        ("n", "a b"),
        ("n", "a\tb"),
        ("n", "a\nb"),
        ("n", "a\x00b"),
        ("n", "x" * 201),
    ],
)
def test_rejects_empty_spaced_control_or_long_parts(name: str, key: str) -> None:
    with pytest.raises(ValueError, match="workflow id"):
        workflow_id(name, U1, key)


def test_accepts_key_of_max_length() -> None:
    assert workflow_id("n", U1, "x" * 200).endswith("x" * 200)


def test_cross_tenant_collision_is_rejected() -> None:
    # (a-<U2>-b, U1, k) would collide with (a, U2, b-<U1>-k) if names could embed UUIDs.
    with pytest.raises(ValueError, match="workflow id"):
        workflow_id(f"a-{U2}-b", U1, "k")


def test_key_may_not_contain_the_tenant_uuid() -> None:
    with pytest.raises(ValueError, match="workflow id"):
        workflow_id("n", U1, f"x-{U1}-y")


@pytest.mark.parametrize("name", ["Upper", "1abc", "a--b", "a-", "-a", "a b", "a.b"])
def test_rejects_malformed_names(name: str) -> None:
    with pytest.raises(ValueError, match="workflow id"):
        workflow_id(name, U1, "k")


def test_tenant_must_be_a_uuid_instance() -> None:
    with pytest.raises(TypeError, match="workflow id"):
        workflow_id("n", str(U1), "k")  # type: ignore[arg-type]

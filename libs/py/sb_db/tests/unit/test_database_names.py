import pytest

from sb_db.database import ensure_database


@pytest.mark.parametrize(
    ("name", "owner"), [('x"; DROP DATABASE y; --', "sb_app"), ("svc", "Bad-Owner")]
)
async def test_ensure_database_rejects_unsafe_identifiers_before_connecting(
    name: str, owner: str
) -> None:
    with pytest.raises(ValueError, match="simple lowercase identifiers"):
        await ensure_database("postgresql+asyncpg://nobody@127.0.0.1:1/none", name, owner=owner)

from sb_db.database import ensure_database


async def test_ensure_database_is_idempotent(postgres_url: str) -> None:
    assert await ensure_database(postgres_url, "svc_example", owner="sb_admin") is True
    assert await ensure_database(postgres_url, "svc_example", owner="sb_admin") is False


async def test_ensure_database_accepts_a_plain_postgresql_url(postgres_url: str) -> None:
    plain = postgres_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    assert await ensure_database(plain, "svc_plain_url", owner="sb_admin") is True

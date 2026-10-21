import asyncpg
from confluent_kafka.admin import AdminClient


async def test_postgres_container_has_app_role_without_bypassrls(postgres_url: str) -> None:
    conn = await asyncpg.connect(postgres_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        row = await conn.fetchrow(
            "select rolsuper, rolbypassrls from pg_roles where rolname = 'sb_app'"
        )
        assert row is not None
        assert row["rolsuper"] is False
        assert row["rolbypassrls"] is False
    finally:
        await conn.close()


def test_kafka_container_answers(kafka_bootstrap: str) -> None:
    metadata = AdminClient({"bootstrap.servers": kafka_bootstrap}).list_topics(timeout=10)
    assert metadata.brokers


async def test_app_connection_is_not_superuser(postgres_app_url: str) -> None:
    conn = await asyncpg.connect(postgres_app_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        assert await conn.fetchval("select current_setting('is_superuser')") == "off"
        assert await conn.fetchval("select current_user") == "sb_app"
    finally:
        await conn.close()


async def test_container_has_the_compose_roles_with_their_attributes(postgres_url: str) -> None:
    conn = await asyncpg.connect(postgres_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        rows = await conn.fetch(
            "select rolname, rolcanlogin, rolcreatedb, rolbypassrls, rolsuper from pg_roles "
            "where rolname in ('sb_migrator', 'sb_app', 'sb_readonly') order by rolname"
        )
        app_can_create = await conn.fetchval(
            "select has_schema_privilege('sb_app', 'public', 'CREATE')"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("sb_app", True, False, False, False),
        ("sb_migrator", True, True, True, False),
        ("sb_readonly", True, False, False, False),
    ]
    assert app_can_create is False


async def test_migrator_url_connects_as_sb_migrator(postgres_migrator_url: str) -> None:
    conn = await asyncpg.connect(postgres_migrator_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        assert await conn.fetchval("select current_user") == "sb_migrator"
        async with conn.transaction():  # owns the database, like a service database
            await conn.execute("create table migrator_probe (id int)")
            await conn.execute("drop table migrator_probe")
    finally:
        await conn.close()

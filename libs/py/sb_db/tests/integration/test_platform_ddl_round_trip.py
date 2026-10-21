"""platform_table_ddl() and its downgrade round-trip on a real Postgres, twice (M9)."""

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sb_db.platform import install_platform_tables
from sb_db.rls import platform_table_ddl, platform_table_ddl_downgrade

SCHEMA = "sb_db_ddl_rt"


async def _state(conn: AsyncConnection) -> tuple[int, int, int, int]:
    """(policies, append-only triggers, functions, tables with RLS enabled) in SCHEMA."""
    policies = (
        await conn.execute(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = :s"), {"s": SCHEMA}
        )
    ).scalar_one()
    triggers = (
        await conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND NOT t.tgisinternal"
            ),
            {"s": SCHEMA},
        )
    ).scalar_one()
    functions = (
        await conn.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname LIKE :p"), {"p": f"{SCHEMA}_%"}
        )
    ).scalar_one()
    rls = (
        await conn.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND (c.relrowsecurity OR c.relforcerowsecurity)"
            ),
            {"s": SCHEMA},
        )
    ).scalar_one()
    return policies, triggers, functions, rls


async def test_upgrade_downgrade_round_trips_and_downgrade_is_idempotent(
    admin_engine: AsyncEngine,
) -> None:
    metadata = MetaData(schema=SCHEMA)
    install_platform_tables(metadata)
    async with admin_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            await conn.run_sync(metadata.create_all)
            for _ in range(2):
                for statement in platform_table_ddl(SCHEMA):
                    await conn.execute(text(statement))
                assert await _state(conn) == (2, 2, 1, 2)
                for statement in [*platform_table_ddl_downgrade(SCHEMA)] * 2:  # idempotent
                    await conn.execute(text(statement))
                assert await _state(conn) == (0, 0, 0, 0)
        finally:
            await transaction.rollback()

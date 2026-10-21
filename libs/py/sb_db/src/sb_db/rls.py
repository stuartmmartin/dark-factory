"""Row-level security and append-only DDL helpers (A13). FORCE makes owners obey RLS too.

Table names come from our own code (migrations) and are still validated as plain
identifiers (optionally `schema.table`). The runtime role `sb_app` is NOBYPASSRLS; the
migration role `sb_migrator` has BYPASSRLS so migrations and backfills see every tenant's rows.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import TextClause, text

TENANT_SETTING = "app.tenant_id"
_TENANT_EXPR = f"NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid"
_PART = r"[a-z_][a-z0-9_]{0,62}"
_TABLE = re.compile(rf"{_PART}(\.{_PART})?")
_MAX_IDENTIFIER_BYTES = 63  # Postgres NAMEDATALEN - 1; longer names are silently truncated
_POLICY_SUFFIX = "_tenant_isolation"
_APPEND_ONLY_SUFFIX = "_append_only"
_TRUNCATE_SUFFIX = "_append_only_truncate"


def _checked(table: str, longest_suffix: str) -> tuple[str, str]:
    """(table as written, a dot-free prefix for derived policy/function/trigger names).

    Rejects a derived name over 63 bytes: Postgres would truncate it, and two long tables
    could then collide on one policy or trigger name.
    """
    if not _TABLE.fullmatch(table):
        raise ValueError(f"unsafe table name {table!r}: expected [schema.]table in lowercase")
    prefix = table.replace(".", "_")
    derived = prefix + longest_suffix
    if len(derived.encode()) > _MAX_IDENTIFIER_BYTES:
        raise ValueError(
            f"derived identifier {derived!r} is longer than {_MAX_IDENTIFIER_BYTES} bytes"
        )
    return table, prefix


def enable_rls_sql(table: str) -> list[str]:
    table, prefix = _checked(table, _POLICY_SUFFIX)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {prefix}{_POLICY_SUFFIX} ON {table} "
        f"USING (tenant_id = {_TENANT_EXPR}) WITH CHECK (tenant_id = {_TENANT_EXPR})",
    ]


def append_only_sql(table: str) -> list[str]:
    """Block UPDATE, DELETE (per row) and TRUNCATE (per statement), even for the owner."""
    table, prefix = _checked(table, _TRUNCATE_SUFFIX)
    function = f"{prefix}{_APPEND_ONLY_SUFFIX}"
    return [
        f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN RAISE EXCEPTION '{table} is append-only'; END $$",
        f"CREATE TRIGGER {function} BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {function}()",
        f"CREATE TRIGGER {prefix}{_TRUNCATE_SUFFIX} BEFORE TRUNCATE ON {table} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {function}()",
    ]


def platform_table_ddl(schema: str | None = None) -> list[str]:
    """The required RLS and append-only state of the platform tables.

    Every service's initial migration applies this after creating the platform tables
    (`install_platform_tables`): RLS on `audit_events` and `idempotency_keys`, and
    `audit_events` append-only. `schema` optionally qualifies the tables.
    """
    audit, keys = _platform_tables(schema)
    return [*enable_rls_sql(audit), *enable_rls_sql(keys), *append_only_sql(audit)]


def platform_table_ddl_downgrade(schema: str | None = None) -> list[str]:
    """Undo `platform_table_ddl()`: drop its triggers, function and policies, disable RLS.

    Idempotent (`IF EXISTS`), so a downgrade can be re-run. It expects the tables to exist:
    run it before the migration drops them.
    """
    audit, keys = _platform_tables(schema)
    return [
        *_append_only_downgrade_sql(audit),
        *_rls_downgrade_sql(keys),
        *_rls_downgrade_sql(audit),
    ]


def _platform_tables(schema: str | None) -> tuple[str, str]:
    prefix = f"{schema}." if schema else ""
    return f"{prefix}audit_events", f"{prefix}idempotency_keys"


def _rls_downgrade_sql(table: str) -> list[str]:
    table, prefix = _checked(table, _POLICY_SUFFIX)
    return [
        f"DROP POLICY IF EXISTS {prefix}{_POLICY_SUFFIX} ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]


def _append_only_downgrade_sql(table: str) -> list[str]:
    table, prefix = _checked(table, _TRUNCATE_SUFFIX)
    function = f"{prefix}{_APPEND_ONLY_SUFFIX}"
    return [
        f"DROP TRIGGER IF EXISTS {function} ON {table}",
        f"DROP TRIGGER IF EXISTS {prefix}{_TRUNCATE_SUFFIX} ON {table}",
        f"DROP FUNCTION IF EXISTS {function}()",
    ]


class _Executes(Protocol):
    def execute(self, statement: TextClause, /) -> object: ...


def apply(target: _Executes, statements: Iterable[str]) -> None:
    """Run DDL from Alembic (`op`) or a sync connection, in order."""
    for statement in statements:
        target.execute(text(statement))

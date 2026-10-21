import pytest

from sb_db.rls import (
    append_only_sql,
    apply,
    enable_rls_sql,
    platform_table_ddl,
    platform_table_ddl_downgrade,
)


def test_enable_rls_forces_policy_even_for_owner() -> None:
    sql = " ".join(enable_rls_sql("journal_entries"))
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "NULLIF(current_setting('app.tenant_id', true), '')::uuid" in sql
    assert "WITH CHECK" in sql


def test_append_only_trigger_blocks_update_and_delete() -> None:
    sql = " ".join(append_only_sql("postings"))
    assert "BEFORE UPDATE OR DELETE ON postings" in sql
    assert "postings is append-only" in sql


def test_append_only_trigger_blocks_truncate() -> None:
    sql = " ".join(append_only_sql("postings"))
    assert (
        "CREATE TRIGGER postings_append_only_truncate BEFORE TRUNCATE ON postings "
        "FOR EACH STATEMENT EXECUTE FUNCTION postings_append_only()"
    ) in sql


def test_schema_qualified_names_derive_underscored_object_names() -> None:
    rls = " ".join(enable_rls_sql("ledger.postings"))
    assert "ALTER TABLE ledger.postings FORCE ROW LEVEL SECURITY" in rls
    assert "CREATE POLICY ledger_postings_tenant_isolation ON ledger.postings" in rls
    append = " ".join(append_only_sql("ledger.postings"))
    assert "FUNCTION ledger_postings_append_only()" in append
    assert "BEFORE UPDATE OR DELETE ON ledger.postings" in append


@pytest.mark.parametrize(
    "table", ["x; DROP TABLE y", "Postings", "a.b.c", "1abc", "", "a..b", "p-q"]
)
def test_ddl_helpers_reject_unsafe_table_names(table: str) -> None:
    with pytest.raises(ValueError, match="table name"):
        enable_rls_sql(table)
    with pytest.raises(ValueError, match="table name"):
        append_only_sql(table)


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object, /) -> None:
        self.statements.append(str(statement))


def test_apply_executes_each_statement_in_order() -> None:
    recorder = _Recorder()
    apply(recorder, ["SELECT 1", "SELECT 2"])
    assert recorder.statements == ["SELECT 1", "SELECT 2"]


def test_platform_table_ddl_is_the_required_state() -> None:
    assert platform_table_ddl() == [
        *enable_rls_sql("audit_events"),
        *enable_rls_sql("idempotency_keys"),
        *append_only_sql("audit_events"),
    ]


def test_platform_table_ddl_qualifies_and_validates_schema() -> None:
    assert platform_table_ddl("svc") == [
        *enable_rls_sql("svc.audit_events"),
        *enable_rls_sql("svc.idempotency_keys"),
        *append_only_sql("svc.audit_events"),
    ]
    with pytest.raises(ValueError, match="unsafe table name"):
        platform_table_ddl("x; DROP TABLE y")


def test_derived_identifiers_longer_than_63_bytes_are_rejected() -> None:
    # Postgres truncates identifiers to 63 bytes, so two long names could silently collide.
    table = "t" * 50  # a valid table name, but "<table>_tenant_isolation" is 67 bytes
    with pytest.raises(ValueError, match="63"):
        enable_rls_sql(table)
    with pytest.raises(ValueError, match="63"):
        append_only_sql(table)
    longest_ok = "t" * (63 - len("_append_only_truncate"))
    assert append_only_sql(longest_ok)
    assert enable_rls_sql(longest_ok)


def test_platform_downgrade_drops_what_the_upgrade_creates_idempotently() -> None:
    sql = platform_table_ddl_downgrade("svc")
    joined = " ".join(sql)
    assert "DROP TRIGGER IF EXISTS svc_audit_events_append_only ON svc.audit_events" in joined
    assert "DROP TRIGGER IF EXISTS svc_audit_events_append_only_truncate" in joined
    assert "DROP FUNCTION IF EXISTS svc_audit_events_append_only()" in joined
    assert "DROP POLICY IF EXISTS svc_audit_events_tenant_isolation ON svc.audit_events" in joined
    assert (
        "DROP POLICY IF EXISTS svc_idempotency_keys_tenant_isolation ON svc.idempotency_keys"
        in joined
    )
    assert "ALTER TABLE svc.idempotency_keys DISABLE ROW LEVEL SECURITY" in joined
    assert all(" IF EXISTS " in s or s.startswith("ALTER TABLE") for s in sql)

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import MetaData

from sb_db.audit import SqlAuditLog
from sb_db.platform import install_platform_tables
from sb_kernel.clock import FixedClock
from sb_kernel.context import RequestContext


def _log() -> SqlAuditLog:
    ctx = RequestContext(tenant_id=UUID(int=1), actor="a", request_id="r")
    return SqlAuditLog(
        install_platform_tables(MetaData()), ctx, FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    )


def test_record_rejects_bad_values_at_record_time() -> None:
    with pytest.raises(TypeError, match="float"):
        _log().record(action="a", entity_type="e", entity_id="1", before=None, after={"x": 1.5})

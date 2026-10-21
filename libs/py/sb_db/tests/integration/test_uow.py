from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sb_db.platform import PlatformTables
from sb_db.uow import SqlAlchemyUnitOfWork, joined
from sb_kernel.clock import Clock
from sb_kernel.context import RequestContext, use_context
from sb_kernel.events import DomainEvent
from sb_kernel.uow import UnitOfWork

type Sessions = async_sessionmaker[AsyncSession]


class WidgetMade(DomainEvent):
    event_type = "test.widget.made"
    widget_id: str

    def event_key(self) -> str:
        return self.widget_id


def ctx(tenant: UUID) -> RequestContext:
    return RequestContext(tenant_id=tenant, actor="tester", request_id="req-1")


async def test_commit_writes_business_row_audit_and_outbox_atomically(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    widgets_table: Table,
    tenant_a: UUID,
) -> None:
    widget_id = str(uuid4())
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.session.execute(
                insert(widgets_table).values(id=UUID(widget_id), tenant_id=tenant_a, name="w")
            )
            uow.audit.record(
                action="widget.create",
                entity_type="widget",
                entity_id=widget_id,
                before=None,
                after={"name": "w"},
            )
            uow.outbox.add(WidgetMade(widget_id=widget_id))
            await uow.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            outbox = (
                await uow.session.execute(
                    select(platform.outbox.c.topic, platform.outbox.c.key).where(
                        platform.outbox.c.key == widget_id
                    )
                )
            ).one()
            audits = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(platform.audit_events)
                    .where(platform.audit_events.c.entity_id == widget_id)
                )
            ).scalar_one()
    assert tuple(outbox) == ("test.widget.made.v1", widget_id)
    assert audits == 1


async def test_exception_rolls_back_everything(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    widgets_table: Table,
    tenant_a: UUID,
) -> None:
    widget_id = str(uuid4())

    async def write_then_fail() -> None:
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.session.execute(
                insert(widgets_table).values(id=UUID(widget_id), tenant_id=tenant_a, name="w")
            )
            uow.outbox.add(WidgetMade(widget_id=widget_id))
            raise RuntimeError("boom")

    with use_context(ctx(tenant_a)):
        with pytest.raises(RuntimeError, match="boom"):
            await write_then_fail()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            outbox_rows = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(platform.outbox)
                    .where(platform.outbox.c.key == widget_id)
                )
            ).scalar_one()
            widget_rows = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(widgets_table)
                    .where(widgets_table.c.id == UUID(widget_id))
                )
            ).scalar_one()
    assert (outbox_rows, widget_rows) == (0, 0)


async def test_leaving_without_commit_discards_writes(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    widgets_table: Table,
    tenant_a: UUID,
) -> None:
    widget_id = uuid4()
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            await uow.session.execute(
                insert(widgets_table).values(id=widget_id, tenant_id=tenant_a, name="w")
            )
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            n = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(widgets_table)
                    .where(widgets_table.c.id == widget_id)
                )
            ).scalar_one()
    assert n == 0


def _conforms_to_kernel_protocol(uow: SqlAlchemyUnitOfWork) -> UnitOfWork:
    return uow  # pyright proves SqlAlchemyUnitOfWork satisfies sb_kernel.uow.UnitOfWork


async def _outbox_rows(uow: SqlAlchemyUnitOfWork, platform: PlatformTables, key: str) -> int:
    return (
        await uow.session.execute(
            select(func.count()).select_from(platform.outbox).where(platform.outbox.c.key == key)
        )
    ).scalar_one()


async def test_rollback_discards_buffers_and_finishes_the_uow(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_a: UUID
) -> None:
    widget_id = str(uuid4())
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.outbox.add(WidgetMade(widget_id=widget_id))
            await uow.rollback()
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                await uow.commit()
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                await uow.rollback()
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                uow.outbox.add(WidgetMade(widget_id=widget_id))
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                uow.audit.record(
                    action="a", entity_type="e", entity_id="1", before=None, after=None
                )
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as check:
            assert await _outbox_rows(check, platform, widget_id) == 0


async def test_commit_finishes_the_uow_but_a_later_rollback_is_a_no_op(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_a: UUID
) -> None:
    widget_id = str(uuid4())
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.outbox.add(WidgetMade(widget_id=widget_id))
            await uow.commit()
            await uow.rollback()  # no-op after commit
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                await uow.commit()
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                uow.outbox.add(WidgetMade(widget_id=widget_id))
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as check:
            assert await _outbox_rows(check, platform, widget_id) == 1


async def test_reentering_the_same_uow_raises(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_a: UUID
) -> None:
    uow = SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock)
    with use_context(ctx(tenant_a)):
        async with uow:
            with pytest.raises(RuntimeError, match="already entered"):
                async with uow:
                    pass
        with pytest.raises(RuntimeError, match="already entered"):
            async with uow:
                pass


async def test_record_snapshots_the_payload_at_record_time(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_a: UUID
) -> None:
    entity_id = str(uuid4())
    after: dict[str, object] = {"name": "before-mutation"}
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.audit.record(
                action="widget.rename",
                entity_type="widget",
                entity_id=entity_id,
                before=None,
                after=after,
            )
            after["name"] = "mutated"
            await uow.commit()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            stored = (
                await uow.session.execute(
                    select(platform.audit_events.c.after).where(
                        platform.audit_events.c.entity_id == entity_id
                    )
                )
            ).scalar_one()
    assert stored == {"name": "before-mutation"}


async def test_rollback_after_a_failed_commit_is_a_no_op_and_nothing_is_written(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    tenant_a: UUID,
    tenant_b: UUID,
) -> None:
    widget_id = str(uuid4())
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            uow.outbox.add(WidgetMade(widget_id=widget_id))
            uow.audit.record(
                action="a", entity_type="e", entity_id=widget_id, before=None, after={"x": 1}
            )
            # Make the commit fail inside the flush: another tenant's row violates RLS.
            await uow.session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_b)}
            )
            with pytest.raises(DBAPIError, match="row-level security"):
                await uow.commit()
            await uow.rollback()  # no-op after a commit attempt
            with pytest.raises(RuntimeError, match="unit of work already finished"):
                uow.outbox.add(WidgetMade(widget_id=widget_id))
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as check:
            assert await _outbox_rows(check, platform, widget_id) == 0


async def test_joined_view_refuses_use_before_entry_and_after_the_outer_uow_finished(
    app_sessions: Sessions, platform: PlatformTables, fake_clock: Clock, tenant_a: UUID
) -> None:
    with use_context(ctx(tenant_a)):
        outer = SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock)
        with pytest.raises(RuntimeError, match="outer unit of work is not active"):
            async with joined(outer)():
                pass
        async with outer:
            await outer.commit()
        with pytest.raises(RuntimeError, match="outer unit of work is not active"):
            async with joined(outer)():
                pass


async def test_joined_view_is_the_outer_uow_and_its_commit_and_rollback_are_no_ops(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    widgets_table: Table,
    tenant_a: UUID,
) -> None:
    widget_id = uuid4()
    with use_context(ctx(tenant_a)):
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as outer:
            async with joined(outer)() as inner:
                assert inner is outer
                await inner.session.execute(
                    insert(widgets_table).values(id=widget_id, tenant_id=tenant_a, name="j")
                )
                await inner.commit()  # no-op: the outer owns the commit
                await inner.rollback()  # no-op too
            await outer.commit()  # still usable, so the inner commit really was a no-op
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            found = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(widgets_table)
                    .where(widgets_table.c.id == widget_id)
                )
            ).scalar_one()
    assert found == 1


async def test_an_error_inside_the_joined_view_propagates_and_rolls_back_the_outer(
    app_sessions: Sessions,
    platform: PlatformTables,
    fake_clock: Clock,
    widgets_table: Table,
    tenant_a: UUID,
) -> None:
    widget_id = uuid4()
    with use_context(ctx(tenant_a)):

        async def write_then_fail() -> None:
            async with (
                SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as outer,
                joined(outer)() as inner,
            ):
                await inner.session.execute(
                    insert(widgets_table).values(id=widget_id, tenant_id=tenant_a, name="j")
                )
                raise RuntimeError("inside")

        with pytest.raises(RuntimeError, match="inside"):
            await write_then_fail()
        async with SqlAlchemyUnitOfWork(app_sessions, platform, fake_clock) as uow:
            found = (
                await uow.session.execute(
                    select(func.count())
                    .select_from(widgets_table)
                    .where(widgets_table.c.id == widget_id)
                )
            ).scalar_one()
    assert found == 0

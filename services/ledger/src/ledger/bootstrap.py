"""Composition root: builds the container (engine, unit of work, use cases) and the API app.

`RecordAccountOpened` is not in the container: the consumer builds it per message around
`sb_db.uow.joined(uow)` (D13).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ledger.application.use_cases.get_account import GetAccount
from ledger.application.use_cases.get_account_balance import GetAccountBalance
from ledger.application.use_cases.list_accounts import ListAccounts
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.post_journal_entry import PostJournalEntry
from ledger.application.use_cases.snapshot_account_count import SnapshotAccountCount
from ledger.infrastructure.models import platform
from ledger.infrastructure.settings import Settings
from ledger.infrastructure.uow import SqlLedgerUnitOfWork
from ledger.interface.admin.acceptors import ACCEPTORS
from ledger.interface.admin.views import AccountAdmin
from ledger.interface.http.routes import router
from sb_admin.admin import create_admin
from sb_admin.auth import DevAdminAuth
from sb_db.engine import create_engine, session_factory
from sb_http.app import create_app, mount_admin
from sb_http.auth import backend_for
from sb_kernel.clock import Clock, SystemClock

__all__ = ["Container", "build_api", "build_container"]

__version__ = version("ledger")


@dataclass(frozen=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    # A SqlAlchemyUnitOfWork factory: the consumer's `U` is bound to it (D11), and it is also a
    # valid `UowFactory` for the use cases.
    uow_factory: Callable[[], SqlLedgerUnitOfWork]
    open_account: OpenAccount
    get_account: GetAccount
    list_accounts: ListAccounts
    post_journal_entry: PostJournalEntry
    get_account_balance: GetAccountBalance
    snapshot_account_count: SnapshotAccountCount


def build_container(settings: Settings) -> Container:
    # The sb_app role, so RLS applies. Never echo=True (D19).
    engine = create_engine(settings.database_url.get_secret_value())
    sessions = session_factory(engine)
    clock = SystemClock()

    def uow_factory() -> SqlLedgerUnitOfWork:
        return SqlLedgerUnitOfWork(sessions, platform, clock)

    return Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        clock=clock,
        uow_factory=uow_factory,
        open_account=OpenAccount(uow_factory, clock),
        get_account=GetAccount(uow_factory),
        list_accounts=ListAccounts(uow_factory),
        post_journal_entry=PostJournalEntry(uow_factory, clock),
        get_account_balance=GetAccountBalance(uow_factory),
        snapshot_account_count=SnapshotAccountCount(uow_factory),
    )


def build_api(settings: Settings, container: Container | None = None) -> FastAPI:
    # First, so prod (oidc, not implemented) fails before any engine is built (D1).
    auth = backend_for(settings.auth_mode, settings.environment)
    # The admin is mounted only outside prod (DevAdminAuth raises elsewhere, D8); its credentials
    # are checked here, before anything is built, because only the API process receives them.
    admin = settings.admin_credentials() if settings.environment != "prod" else None
    services = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            await services.engine.dispose()

    async def db_ready() -> bool:  # bounded by create_app's readiness_timeout (2 s)
        async with services.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    # create_app installs RequestContextMiddleware itself (D3).
    app = create_app(
        title="ledger",
        version=__version__,
        routers=[router],
        auth=auth,
        readiness=[db_ready],
        lifespan=lifespan,
        expose_docs=settings.environment != "prod",
    )
    app.state.container = services
    if admin is not None:
        admin_auth = DevAdminAuth(
            admin.secret_key, admin.username, admin.password, environment=settings.environment
        )
        # On the sb_app engine: RLS shows the admin zero rows (D9). Never the migrator URL.
        mount_admin(
            app,
            create_admin(
                services.engine,
                title="ledger admin",
                auth=admin_auth,
                acceptors=ACCEPTORS,
                views=[AccountAdmin],
                mount_path="/admin",
            ),
        )
    return app

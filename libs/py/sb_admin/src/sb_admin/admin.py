"""SQLAdmin factory returning a standalone, self-authenticating ASGI app."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqladmin import Admin, ModelView
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette

from sb_admin.acceptor import Acceptor, acceptor_view
from sb_admin.auth import DevAdminAuth

__all__ = ["TEMPLATES_DIR", "create_admin"]

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_admin(
    engine: AsyncEngine,
    *,
    title: str,
    auth: DevAdminAuth,
    acceptors: Sequence[Acceptor] = (),
    views: Sequence[type[ModelView]] = (),
    mount_path: str = "/admin",
) -> Starlette:
    """Build the admin as its own ASGI app; the caller mounts it (e.g. sb_http.mount_admin).

    SQLAdmin attaches itself to a host app at ``base_url``. The host here is private and
    the admin sits at its root (``base_url=""``), so the returned app can be mounted at any
    path. It carries its own session authentication (``auth``); nothing else guards it.

    ``mount_path`` scopes the session cookie and is recorded as ``app.state.mount_path``, so
    ``sb_http.mount_admin(app, admin_app)`` mounts it there. ``auth`` is not modified: the
    admin gets its own copy bound to ``mount_path``, so one auth object can serve several.
    """
    bound = auth.for_mount_path(mount_path)
    host = Starlette()
    host.state.mount_path = mount_path
    admin = Admin(
        host,
        engine,
        base_url="",
        title=title,
        authentication_backend=bound,
        templates_dir=str(TEMPLATES_DIR),
    )
    for acceptor in acceptors:
        admin.add_base_view(acceptor_view(acceptor))
    for view in views:
        admin.add_view(view)
    return host

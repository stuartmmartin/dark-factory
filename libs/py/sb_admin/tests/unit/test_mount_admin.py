"""Admin mounted into a real sb_http app: public mount, own auth, API still guarded."""

from collections.abc import Callable
from uuid import uuid4

import httpx
from fastapi import APIRouter, FastAPI
from starlette.applications import Starlette

from sb_http.app import create_app, mount_admin
from sb_http.auth import DevHeaderAuth


def _app(admin: Starlette) -> FastAPI:
    router = APIRouter()

    @router.get("/things", operation_id="list_things")
    async def things() -> dict[str, str]:
        return {"ok": "yes"}

    app = create_app(title="t", version="1", routers=[router], auth=DevHeaderAuth("test"))
    mount_admin(app, admin)
    return app


async def test_admin_is_public_to_sb_http_but_guarded_by_its_own_login(
    admin_asgi: Starlette,
) -> None:
    transport = httpx.ASGITransport(app=_app(admin_asgi))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/admin/login")).status_code == 200  # no sb_http headers
        anon = await c.get("/admin/acceptors/split")
        assert anon.status_code == 302
        assert "/login" in anon.headers["location"]
        login = await c.post("/admin/login", data={"username": "admin", "password": "pw"})
        assert login.status_code == 302
        page = await c.get("/admin/acceptors/split")
        assert page.status_code == 200
        assert 'name="total"' in page.text
        computed = await c.post("/admin/acceptors/split", data={"total": "9", "parts": "3"})
        assert computed.status_code == 200
        assert "3" in computed.text


async def test_normal_api_route_still_needs_tenant_header(admin_asgi: Starlette) -> None:
    transport = httpx.ASGITransport(app=_app(admin_asgi))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Even after admin login, the API is not opened up by the admin session.
        await c.post("/admin/login", data={"username": "admin", "password": "pw"})
        assert (await c.get("/things")).status_code == 403
        ok = await c.get("/things", headers={"X-Tenant-Id": str(uuid4())})
        assert ok.status_code == 200


async def test_mount_admin_follows_the_admin_apps_mount_path(
    make_admin: Callable[..., Starlette],
) -> None:
    app = create_app(title="t", version="1", routers=[], auth=DevHeaderAuth("test"))
    mount_admin(app, make_admin(mount_path="/ops"))  # no second path argument needed
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        login = await c.post("/ops/login", data={"username": "admin", "password": "pw"})
        assert login.status_code == 302
        assert "path=/ops" in login.headers["set-cookie"].lower()
        assert (await c.get("/ops/acceptors/split")).status_code == 200

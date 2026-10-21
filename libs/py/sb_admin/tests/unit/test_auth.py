import hmac
from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

from sb_admin.admin import create_admin
from sb_admin.auth import DevAdminAuth


async def test_wrong_password_fails_login(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/admin/login", data={"username": "admin", "password": "nope"})
    assert response.status_code == 400
    assert (await anon.get("/admin/acceptors/split")).status_code == 302


async def test_right_password_sets_session(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/admin/login", data={"username": "admin", "password": "pw"})
    assert response.status_code == 302
    assert "sb_admin_session=" in response.headers["set-cookie"]
    assert (await anon.get("/admin/acceptors/split")).status_code == 200


async def test_login_failure_does_not_reveal_which_field(anon: httpx.AsyncClient) -> None:
    bad_user = await anon.post("/admin/login", data={"username": "x", "password": "pw"})
    bad_pass = await anon.post("/admin/login", data={"username": "admin", "password": "x"})
    assert bad_user.status_code == bad_pass.status_code == 400
    assert bad_user.text == bad_pass.text


async def test_non_ascii_credentials_do_not_crash(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/admin/login", data={"username": "admïn", "password": "é"})
    assert response.status_code == 400


async def test_logout_ends_session(client: httpx.AsyncClient) -> None:
    await client.get("/admin/logout")
    assert (await client.get("/admin/acceptors/split")).status_code == 302


@pytest.mark.parametrize("env", ["prod", "production", "staging", "", "loca1"])
def test_refuses_non_dev_environments(env: str) -> None:
    with pytest.raises(ValueError, match="only allowed"):
        DevAdminAuth("k" * 32, "a", "b", environment=env)


def test_refuses_short_secret() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        DevAdminAuth("short", "a", "b", environment="test")


def test_refuses_empty_credentials() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        DevAdminAuth("k" * 32, "", "", environment="test")


@pytest.mark.parametrize("env", ["local", " LOCAL ", "Dev", "test", "ci", "CI"])
def test_accepts_dev_environments_normalised(env: str) -> None:
    DevAdminAuth("k" * 32, "a", "b", environment=env)


def _login_request(
    username: str, password: str, session: dict[str, object] | None = None
) -> Request:
    body = f"username={username}&password={password}".encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/login",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "session": {} if session is None else session,
    }
    return Request(scope, receive)  # type: ignore[arg-type]


async def test_both_credentials_compared_even_when_user_wrong(
    monkeypatch: pytest.MonkeyPatch,
    make_auth: Callable[..., DevAdminAuth],
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert await make_auth().login(_login_request("wrong", "pw")) is False
    assert len(calls) == 2


async def test_login_discards_preexisting_session_state(
    make_auth: Callable[..., DevAdminAuth],
) -> None:
    request = _login_request("admin", "pw", {"planted": "fixation"})
    assert await make_auth().login(request) is True
    assert "planted" not in request.session


async def test_failed_login_leaves_session_unauthenticated(
    make_auth: Callable[..., DevAdminAuth],
) -> None:
    request = _login_request("admin", "bad")
    auth = make_auth()
    assert await auth.login(request) is False
    assert await auth.authenticate(request) is False


async def test_cookie_attributes_on_real_set_cookie_header(anon: httpx.AsyncClient) -> None:
    response = await anon.post("/admin/login", data={"username": "admin", "password": "pw"})
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("sb_admin_session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=28800" in cookie
    assert "path=/admin" in cookie
    assert "secure" not in cookie


@pytest.mark.parametrize(
    ("env", "secure"), [("local", False), ("dev", False), ("test", False), ("ci", True)]
)
async def test_secure_flag_by_environment(
    env: str, secure: bool, make_admin: Callable[..., Starlette]
) -> None:
    app = Starlette(routes=[Mount("/admin", app=make_admin(environment=env))])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t") as c:
        response = await c.post("/admin/login", data={"username": "admin", "password": "pw"})
    assert ("secure" in response.headers["set-cookie"].lower()) is secure


async def test_cookie_path_follows_mount_path(make_admin: Callable[..., Starlette]) -> None:
    app = Starlette(routes=[Mount("/ops", app=make_admin(mount_path="/ops"))])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.post("/ops/login", data={"username": "admin", "password": "pw"})
        assert "path=/ops" in response.headers["set-cookie"].lower()
        assert (await c.get("/ops/acceptors/split")).status_code == 200


async def test_one_auth_object_can_serve_admins_at_different_paths(
    make_auth: Callable[..., DevAdminAuth],
) -> None:
    auth = make_auth()
    before = auth.middlewares
    engine = create_async_engine("sqlite+aiosqlite://")
    ops = create_admin(engine, title="t", auth=auth, mount_path="/ops")
    admin = create_admin(engine, title="t", auth=auth, mount_path="/admin")
    app = Starlette(routes=[Mount("/ops", app=ops), Mount("/admin", app=admin)])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        first = await c.post("/ops/login", data={"username": "admin", "password": "pw"})
        second = await c.post("/admin/login", data={"username": "admin", "password": "pw"})
    assert "path=/ops" in first.headers["set-cookie"].lower()
    assert "path=/admin" in second.headers["set-cookie"].lower()
    assert auth.middlewares is before  # create_admin never mutates the shared auth object

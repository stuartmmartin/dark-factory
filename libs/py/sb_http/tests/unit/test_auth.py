from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter

from sb_http.auth import DevHeaderAuth, backend_for
from sb_kernel.context import current_context, optional_context

TID = "11111111-1111-1111-1111-111111111111"


def _router() -> APIRouter:
    r = APIRouter()

    @r.get("/whoami")
    async def whoami() -> dict[str, str]:
        ctx = current_context()
        return {"tenant": str(ctx.tenant_id), "actor": ctx.actor, "rid": ctx.request_id}

    @r.get("/bg")
    async def bg() -> dict[str, str]:
        async def child() -> str:
            return str(current_context().tenant_id)

        return {"tenant": await asyncio.create_task(child())}

    @r.get("/admin-x")
    async def admin_dash_x() -> dict[str, bool]:
        return {"has_ctx": optional_context() is not None}

    @r.get("/health-evil")
    async def health_evil() -> dict[str, bool]:
        return {"has_ctx": optional_context() is not None}

    return r


async def test_missing_tenant_header_is_403(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "forbidden"


async def test_malformed_tenant_uuid_is_403(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": "not-a-uuid"})
    assert resp.status_code == 403


async def test_valid_header_sets_context_in_route(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Actor": "alice"})
    assert resp.status_code == 200
    assert UUID(resp.json()["tenant"]) == UUID(TID)
    assert resp.json()["actor"] == "alice"


async def test_actor_defaults_to_dev(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID})
    assert resp.json()["actor"] == "dev"


async def test_context_visible_to_tasks_spawned_from_request(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/bg", headers={"X-Tenant-Id": TID})
    assert resp.status_code == 200
    assert resp.json()["tenant"] == TID


async def test_context_is_reset_after_route_raises(client_for: Any) -> None:
    r = APIRouter()

    @r.get("/raises")
    async def raises() -> None:
        raise RuntimeError("boom")

    async with client_for(r, raise_app_exceptions=False) as client:
        resp = await client.get("/raises", headers={"X-Tenant-Id": TID})
    assert resp.status_code == 500
    assert optional_context() is None


async def test_context_is_reset_after_request(client_for: Any) -> None:
    async with client_for(_router()) as client:
        await client.get("/whoami", headers={"X-Tenant-Id": TID})
    assert optional_context() is None


async def test_request_id_is_echoed(client_for: Any) -> None:
    rid = str(uuid4())
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Request-Id": rid})
    assert resp.headers["x-request-id"] == rid
    assert resp.json()["rid"] == rid


async def test_request_id_generated_when_absent(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID})
    UUID(resp.headers["x-request-id"])


@pytest.mark.parametrize(
    "bad", ["x" * 129, "has space", "a\tb", "semi;colon", 'quote"', "<script>"]
)
async def test_hostile_request_id_is_replaced(client_for: Any, bad: str) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Request-Id": bad})
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] != bad
    assert resp.json()["rid"] == resp.headers["x-request-id"]
    UUID(resp.headers["x-request-id"])


async def test_request_id_at_limit_is_kept(client_for: Any) -> None:
    rid = "a" * 128
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Request-Id": rid})
    assert resp.headers["x-request-id"] == rid


async def test_health_live_needs_no_header(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200


@pytest.mark.parametrize("path", ["/admin-x", "/health-evil"])
async def test_lookalike_paths_are_not_public(client_for: Any, path: str) -> None:
    async with client_for(_router()) as client:
        resp = await client.get(path)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "env", ["prod", "production", "staging", "", "Prod", "prd", "localhost", "development"]
)
def test_backend_for_dev_outside_allowlist_is_refused(env: str) -> None:
    with pytest.raises(ValueError, match="dev auth"):
        backend_for("dev", env)


@pytest.mark.parametrize("env", ["local", "dev", "test", "ci"])
def test_backend_for_dev_in_allowlisted_env(env: str) -> None:
    assert isinstance(backend_for("dev", env), DevHeaderAuth)


@pytest.mark.parametrize("env", ["prod", "staging", ""])
def test_dev_header_auth_refuses_direct_construction_outside_allowlist(env: str) -> None:
    with pytest.raises(ValueError, match="dev auth"):
        DevHeaderAuth(environment=env)


@pytest.mark.parametrize("actor", ["has space", "a" * 129, "semi;colon", "new\\nline", ""])
async def test_hostile_actor_is_403(client_for: Any, actor: str) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Actor": actor})
    assert resp.status_code == 403


async def test_actor_charset_allows_email_like(client_for: Any) -> None:
    async with client_for(_router()) as client:
        resp = await client.get("/whoami", headers={"X-Tenant-Id": TID, "X-Actor": "a.b@c-d:e_f"})
    assert resp.status_code == 200
    assert resp.json()["actor"] == "a.b@c-d:e_f"


def test_backend_for_oidc_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="OIDC auth is specified separately"):
        backend_for("oidc", "prod")

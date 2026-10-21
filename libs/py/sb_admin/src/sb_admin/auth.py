"""Dev-only admin authentication for SQLAdmin (session login).

DEV ONLY. Known limitations, all acceptable only because construction is refused outside
local/dev/test/ci:

- One shared username/password, no per-user identity.
- The session is a client-side signed cookie (Starlette ``SessionMiddleware``). Logout only
  clears the browser's copy; a captured cookie stays valid until it expires (8 hours).
- SQLAdmin's ``/logout`` is a GET, so it can be triggered cross-site.
- No CSRF protection on the login form or on admin forms (SameSite=lax is the only guard).
- No login throttling and no audit trail.

Production needs: OIDC/SSO, CSRF protection, login throttling, server-side sessions (revocable),
and audit of admin actions.
"""

from __future__ import annotations

import copy
import hmac
from typing import Any

from sqladmin.authentication import AuthenticationBackend
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

__all__ = ["DevAdminAuth"]

# Same allowlist as sb_http's dev auth: anything else (prod, staging, empty, typos) is refused.
_DEV_ENVIRONMENTS = frozenset({"local", "dev", "test", "ci"})
# Environments that may serve the session cookie over plain http; all others get Secure.
_PLAIN_HTTP_ENVIRONMENTS = frozenset({"local", "dev", "test"})
_MIN_SECRET_LENGTH = 32
_SESSION_KEY = "sb_admin_user"
_COOKIE_NAME = "sb_admin_session"


def _same(supplied: object, expected: str) -> bool:
    if not isinstance(supplied, str):
        return False
    return hmac.compare_digest(supplied.encode(), expected.encode())


class DevAdminAuth(AuthenticationBackend):
    """Single shared username/password, signed-cookie session. Constructible only in dev.

    SQLAdmin's default SessionMiddleware settings are: cookie ``session``, max_age 14 days,
    ``SameSite=lax``, ``https_only=False`` (no Secure flag), path ``/``. Here the cookie is
    ``sb_admin_session``, HttpOnly, SameSite=lax, 8 hours, ``Secure`` unless the environment is
    local, dev or test, and scoped to the mount path (``create_admin`` uses
    ``for_mount_path``; default ``/admin``).
    """

    def __init__(self, secret_key: str, username: str, password: str, *, environment: str) -> None:
        env = environment.strip().lower()
        if env not in _DEV_ENVIRONMENTS:
            raise ValueError(
                f"dev admin auth is only allowed in {sorted(_DEV_ENVIRONMENTS)}, "
                f"got {environment!r}"
            )
        if len(secret_key) < _MIN_SECRET_LENGTH:
            raise ValueError(f"secret_key must be at least {_MIN_SECRET_LENGTH} characters")
        if not username or not password:
            raise ValueError("username and password must be non-empty")
        super().__init__(secret_key=secret_key)
        self._secret_key = secret_key
        self._https_only = env not in _PLAIN_HTTP_ENVIRONMENTS
        self.middlewares = self._session_middlewares("/admin")
        self._username = username
        self._password = password

    def for_mount_path(self, mount_path: str) -> DevAdminAuth:
        """A copy whose session cookie is scoped to `mount_path`; this object is unchanged."""
        bound = copy.copy(self)
        bound.middlewares = self._session_middlewares(mount_path)
        return bound

    def _session_middlewares(self, mount_path: str) -> list[Middleware]:
        session_kwargs: dict[str, Any] = {
            "session_cookie": _COOKIE_NAME,
            "https_only": self._https_only,
            "same_site": "lax",
            "max_age": 8 * 60 * 60,
            "path": mount_path,
        }
        return [Middleware(SessionMiddleware, secret_key=self._secret_key, **session_kwargs)]

    async def login(self, request: Request) -> bool:
        form = await request.form()
        # Evaluate both comparisons so timing does not reveal which field was wrong.
        user_ok = _same(form.get("username"), self._username)
        password_ok = _same(form.get("password"), self._password)
        if not (user_ok and password_ok):
            return False
        request.session.clear()  # drop any pre-login session state
        request.session[_SESSION_KEY] = self._username
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return _same(request.session.get(_SESSION_KEY), self._username)

"""The client's one I/O seam: send a JSON request, get a status and a JSON body back.

`Transport` is what the CLI depends on; `UrllibTransport` is the real one (stdlib, with a timeout
on every call, C6). Tests pass an in-memory fake of the API instead.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    body: Any


class TransportError(Exception):
    """The API could not be reached (or answered with something that is not JSON)."""


class Transport(Protocol):
    def __call__(
        self, method: str, path: str, *, body: dict[str, Any] | None, headers: dict[str, str]
    ) -> Reply: ...


class UrllibTransport:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"the ledger URL must be http(s), got {base_url!r}")
        self._base_url, self._timeout = base_url.rstrip("/"), timeout_seconds

    def __call__(
        self, method: str, path: str, *, body: dict[str, Any] | None, headers: dict[str, str]
    ) -> Reply:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        )
        try:
            opened = urllib.request.urlopen(request, timeout=self._timeout)  # noqa: S310 - as above
            with opened as response:
                return Reply(response.status, json.loads(response.read() or b"null"))
        except urllib.error.HTTPError as error:  # a problem+json answer, not a transport failure
            with error:
                return Reply(error.code, _json_or_text(error.read()))
        except (urllib.error.URLError, TimeoutError) as error:
            raise TransportError(f"cannot reach the ledger at {self._base_url}: {error}") from error
        except json.JSONDecodeError as error:
            raise TransportError(f"the ledger answered with invalid JSON: {error}") from error


def _json_or_text(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"code": "http_error", "detail": raw.decode(errors="replace")[:200]}

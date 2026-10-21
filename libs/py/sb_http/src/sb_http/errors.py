"""Map kernel errors to RFC 9457 problem+json, once (C8)."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sb_kernel.errors import Conflict, DomainError, Forbidden, NotFound, ValidationFailed

__all__ = ["PROBLEM_MEDIA_TYPE", "STATUS_BY_ERROR", "install_error_handlers", "problem"]

PROBLEM_MEDIA_TYPE = "application/problem+json"
_MAX_VALIDATION_ERRORS = 20
_MAX_DETAIL_CHARS = 2000

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    NotFound: 404,
    Conflict: 409,
    ValidationFailed: 422,
    Forbidden: 403,
}


def problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        content={
            "type": "about:blank",
            "title": HTTPStatus(status).phrase,
            "status": status,
            "code": code,
            "detail": detail,
        },
    )


def _status_for(exc: DomainError) -> int:
    for cls, status in STATUS_BY_ERROR.items():
        if isinstance(exc, cls):
            return status
    return 400


async def _domain_error(_: Request, e: Exception) -> JSONResponse:
    exc = cast(DomainError, e)
    return problem(_status_for(exc), exc.code, exc.message)


async def _request_validation(_: Request, e: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, e)
    # loc + msg only: never echo the submitted input back.
    parts: list[Any] = [
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
        for err in exc.errors()[:_MAX_VALIDATION_ERRORS]
    ]
    detail = "; ".join(parts)[:_MAX_DETAIL_CHARS] or "invalid request"
    return problem(422, ValidationFailed.code, detail)


def _json_detail(detail: Any) -> str:
    try:
        return json.dumps(detail)
    except (TypeError, ValueError):
        return "error"


async def _http_exception(_: Request, e: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, e)
    codes = {404: NotFound.code, 405: "method_not_allowed"}
    try:
        HTTPStatus(exc.status_code)
    except ValueError:
        return problem(500, "internal_error", "internal error")
    raw_detail: Any = exc.detail
    detail = raw_detail if isinstance(raw_detail, str) else _json_detail(raw_detail)
    response = problem(exc.status_code, codes.get(exc.status_code, "http_error"), detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _request_validation)
    app.add_exception_handler(StarletteHTTPException, _http_exception)

"""Generic acceptor view: lets a human run a pure policy through a form.

The view never touches the database: it parses form input into the policy's pydantic input
model, calls the pure function, and renders inputs, outputs and the version.

Form parsing: values are text. For fields that are not required, an empty string means
"absent", so the model's default applies. ``list[...]`` fields read every submitted value
(``form.getlist``) and also accept one comma-separated value. A list with no non-blank items is
absent too, so a required list left blank is reported as missing (not accepted as ``[]``).
Non-text (file) parts and unknown fields are ignored. Views are fixed when the admin is built
(``views=`` / ``acceptors=`` of ``create_admin``); nothing is registered at runtime.

Errors: a policy refuses input by raising an ``sb_kernel.errors.DomainError`` subclass (e.g.
``ValidationFailed``, ``CurrencyMismatch``), as policies import only the kernel (A2). Its
``message`` is shown with a 422. ``InputRejected`` is the same for interface-layer
acceptor glue (an adapter written in this layer, not a policy). Any other exception
(``ArithmeticError``, a plain ``ValueError``, ...) is logged via sb_obs as
``admin.acceptor_failed`` and shown as a generic "acceptor failed" message, never its text.

Dev-only tool (see ``sb_admin.auth``): no CSRF protection is applied to the form.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Union, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from sqladmin import BaseView, expose
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response

from sb_kernel.errors import DomainError
from sb_obs.logging import get_logger

__all__ = ["Acceptor", "InputRejected", "acceptor_view"]

_log = get_logger("sb_admin.acceptor")
_GENERIC_FAILURE = "acceptor failed (see server logs)"


class InputRejected(ValueError):  # noqa: N818 - an outcome name, like sb_kernel's errors
    """Acceptor glue (interface layer) refusing the input; its message is shown to the user.

    Policies never raise this (they import only sb_kernel, A2): they raise a
    `sb_kernel.errors.DomainError` subclass, which is shown the same way.
    """


@dataclass(frozen=True)
class Acceptor:
    slug: str
    title: str
    input_model: type[BaseModel]
    fn: Callable[[Any], BaseModel]
    version: str
    description: str = ""


def _is_list(info: FieldInfo) -> bool:
    ann = info.annotation
    if get_origin(ann) in (Union, types.UnionType):
        return any(get_origin(a) is list for a in get_args(ann))
    return get_origin(ann) is list


def _parse_form(acceptor: Acceptor, form: FormData) -> dict[str, Any]:
    """Text form -> model input. See the module docstring for the rules."""
    values: dict[str, Any] = {}
    for name, info in acceptor.input_model.model_fields.items():
        if _is_list(info):
            items = [
                part.strip()
                for raw in form.getlist(name)
                if isinstance(raw, str)
                for part in raw.split(",")
            ]
            items = [i for i in items if i]
            if items:  # blank means absent: a required list is then reported missing
                values[name] = items
            continue
        raw_value = form.get(name)
        if not isinstance(raw_value, str):
            continue
        if raw_value == "" and not info.is_required():
            continue
        values[name] = raw_value
    return values


def _display(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in cast("list[object]", value))
    return "" if value is None else str(value)


def _fields(acceptor: Acceptor, values: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "label": info.title or name,
            "help": info.description or "",
            "value": _display(values.get(name)),
        }
        for name, info in acceptor.input_model.model_fields.items()
    ]


def _error_lines(exc: ValidationError) -> list[str]:
    # loc + msg only: never echo `input`, and no exception internals.
    return [f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()]


def acceptor_view(acceptor: Acceptor) -> type[BaseView]:
    async def page(self: BaseView, request: Request) -> Response:
        values: dict[str, Any] = {}
        errors: list[str] = []
        result: dict[str, Any] | None = None
        status = 200
        if request.method == "POST":
            # Close ignored file uploads too; multipart parsing creates temporary files.
            async with request.form() as form:
                values = _parse_form(acceptor, form)
            try:
                out = acceptor.fn(acceptor.input_model.model_validate(values))
                result = out.model_dump(mode="json")
            except ValidationError as exc:
                errors, status = _error_lines(exc), 422
            except InputRejected as exc:
                errors, status = [str(exc)], 422
            except DomainError as exc:  # a policy refusing the input: its message is for users
                errors, status = [exc.message], 422
            except Exception:  # policy is arbitrary code; never leak its text
                _log.exception("admin.acceptor_failed", slug=acceptor.slug)
                errors, status = [_GENERIC_FAILURE], 422
        context = {
            "acceptor": acceptor,
            "fields": _fields(acceptor, values),
            "errors": errors,
            "result": result,
        }
        templates: Any = self.templates  # sqladmin's TemplateResponse is partially untyped
        return await templates.TemplateResponse(
            request, "sb_admin/acceptor.html", context, status_code=status
        )

    name = f"acceptor_{acceptor.slug.replace('-', '_')}"
    page.__name__ = name
    exposed = expose(
        f"/acceptors/{acceptor.slug}", methods=["GET", "POST"], identity=acceptor.slug
    )(page)
    return type(
        f"{acceptor.slug.title().replace('-', '')}Acceptor",
        (BaseView,),
        {
            "name": acceptor.title,
            "category": "Acceptors",
            "icon": "fa-solid fa-circle-check",
            name: exposed,
        },
    )

"""structlog configuration: JSON logs, request context, redaction (C9).

Standard-library logging (SQLAlchemy, uvicorn, temporalio, ...) is routed through the same
processors by a root handler with structlog's `ProcessorFormatter`, so library log lines are
JSON too and are redacted the same way.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO, cast

import structlog

from sb_kernel.context import optional_context
from sb_obs.redaction import redact_processor


def context_processor(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    del logger, method_name
    ctx = optional_context()
    if ctx is not None:
        event_dict.setdefault("tenant_id", str(ctx.tenant_id))
        event_dict.setdefault("request_id", ctx.request_id)
        event_dict.setdefault("actor", ctx.actor)
        if ctx.trace_id:
            event_dict.setdefault("trace_id", ctx.trace_id)
    return event_dict


def configure_logging(
    *, level: str = "INFO", json: bool = True, stream: TextIO | None = None
) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper())
    if numeric is None:
        raise ValueError(f"unknown log level {level!r}")
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        context_processor,
        structlog.processors.format_exc_info,
        redact_processor,
    ]
    out = stream or sys.stdout
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=False,
    )
    _route_stdlib_logging(shared, renderer, out, numeric)


_STDLIB_HANDLER = "sb_obs.structlog"


def _route_stdlib_logging(shared: list[Any], renderer: Any, out: TextIO, level: int) -> None:
    """Replace our root handler (never duplicate it) with one that renders through structlog."""
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(out)
    handler.set_name(_STDLIB_HANDLER)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _STDLIB_HANDLER]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))

"""`python -m ledger.main [--reload]`: run the API with uvicorn (D19).

uvicorn runs with `log_config=None`, so its loggers go through sb_obs's redacting stdlib bridge
instead of uvicorn's own config. The `uvicorn` CLI cannot pass `None`, so always start the
service this way. Importing this module builds nothing.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn
from fastapi import FastAPI

from ledger.bootstrap import build_api
from ledger.infrastructure.settings import load_settings
from sb_obs.logging import configure_logging

__all__ = ["create", "main"]

HOST = "0.0.0.0"  # noqa: S104 - inside the container; compose publishes it on loopback
PORT = 8000
RELOAD_DIRS = ["services/ledger/src", "libs/py"]


def create() -> FastAPI:
    """uvicorn's app factory (`factory=True`), run by the process that serves requests.

    It configures logging itself: under `--reload` uvicorn serves from a child process that
    imports this module fresh and never runs `main()`. `configure_logging` is idempotent (it
    replaces its own root handler), so running it here and in `main()` is safe.
    """
    settings = load_settings()
    configure_logging(level=settings.log_level)
    return build_api(settings)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ledger.main", description="Run the ledger API.")
    parser.add_argument("--reload", action="store_true", help="Reload on source changes (dev).")
    args = parser.parse_args(argv)
    configure_logging(level=load_settings().log_level)  # the supervisor's own logs (reloader)
    uvicorn.run(
        "ledger.main:create",
        factory=True,
        host=HOST,
        port=PORT,
        log_config=None,
        reload=args.reload,
        reload_dirs=RELOAD_DIRS if args.reload else None,
    )


if __name__ == "__main__":
    main()

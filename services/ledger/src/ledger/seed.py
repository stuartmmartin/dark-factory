"""`python -m ledger.seed [--tenant UUID]`: open the demo account for local development.

Under the fixed demo tenant (or `--tenant`), it opens one account, "Operating cash" (USD),
through `OpenAccount` with a fixed idempotency key, so re-running it replays the first result
instead of opening a second account. It prints the tenant id and the account id. It goes
through the use case (audit, outbox, RLS), never raw SQL. Importing this module builds nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from uuid import UUID

from ledger.application.dto import AccountResult, OpenAccountCommand
from ledger.application.use_cases.open_account import OpenAccount
from ledger.bootstrap import build_container
from ledger.infrastructure.settings import Settings, load_settings
from sb_kernel.context import RequestContext, use_context
from sb_obs.logging import configure_logging

__all__ = ["DEMO_TENANT", "SEED_ACCOUNT_NAME", "SEED_KEY", "main", "parse_args", "run", "seed"]

DEMO_TENANT = UUID(int=0xD3)  # 00000000-0000-0000-0000-0000000000d3
SEED_ACCOUNT_NAME = "Operating cash"
SEED_CURRENCY = "USD"
SEED_KEY = "seed-account-1"
SEED_ACTOR = "seed"


async def seed(open_account: OpenAccount, tenant: UUID) -> AccountResult:
    """Open (or replay) the demo account as `tenant`."""
    ctx = RequestContext(tenant_id=tenant, actor=SEED_ACTOR, request_id=SEED_KEY)
    with use_context(ctx):
        return await open_account(
            OpenAccountCommand(
                name=SEED_ACCOUNT_NAME, currency=SEED_CURRENCY, idempotency_key=SEED_KEY
            )
        )


async def run(settings: Settings, tenant: UUID) -> AccountResult:
    container = build_container(settings)
    try:
        return await seed(container.open_account, tenant)
    finally:
        await container.engine.dispose()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ledger.seed", description="Seed demo ledger data.")
    parser.add_argument(
        "--tenant", type=UUID, default=DEMO_TENANT, help=f"tenant id (default {DEMO_TENANT})"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    settings = load_settings()
    configure_logging(level=settings.log_level)
    result = asyncio.run(run(settings, args.tenant))
    print(f"tenant_id={args.tenant}")  # noqa: T201 - the CLI's output
    print(f"account_id={result.id}{' (replayed)' if result.replayed else ''}")  # noqa: T201


if __name__ == "__main__":
    main()

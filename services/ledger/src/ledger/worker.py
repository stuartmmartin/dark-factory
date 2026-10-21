"""`python -m ledger.worker`: the Temporal worker for the ledger's workflows and activities.

It configures redacting logging (D19), connects to Temporal with a bounded wait (C6), binds the
activities to the container, and runs the worker on `settings.task_queue` until SIGTERM or SIGINT.
The engine is disposed on the way out. Nothing here starts workflows; any code that does passes
`rpc_timeout=timedelta(seconds=10)` (D16). Importing this module builds nothing.
"""

from __future__ import annotations

import asyncio
import signal

from ledger.bootstrap import build_container
from ledger.infrastructure.settings import Settings, load_settings
from ledger.interface.workflows import activities
from ledger.interface.workflows.account_count_snapshot import AccountCountSnapshot
from sb_obs.logging import configure_logging
from sb_workflows.client import connect
from sb_workflows.worker import build_worker

__all__ = ["main", "run"]


async def run(settings: Settings) -> None:
    client = await connect(settings.temporal_target, settings.temporal_namespace)
    container = build_container(settings)
    try:
        activities.bind(container)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        worker = build_worker(
            client,
            task_queue=settings.task_queue,
            workflows=[AccountCountSnapshot],
            activities=[activities.snapshot_account_count_activity],
        )
        async with worker:  # leaving the block shuts the worker down
            await stop.wait()
    finally:
        await container.engine.dispose()


def main() -> None:
    settings = load_settings()
    configure_logging(level=settings.log_level)  # D19: this process's own entrypoint
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()

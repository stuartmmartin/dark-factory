"""The relay loop in `python -m ledger.consumer` (D12): polls until stopped, and lets a fatal
`PublishFailed` end it so the supervisor restarts the process."""

import asyncio
import importlib
import json
import logging
import os
import sys
from collections.abc import Iterator

import pytest
import structlog

import ledger.consumer
from ledger.consumer import relay_loop
from ledger.infrastructure.settings import Settings
from sb_messaging.publisher import PublishFailed

# Only what this process gets in compose and k8s: no admin credentials, no privileged URLs.
ENV = {
    "LEDGER_ENVIRONMENT": "test",
    "LEDGER_AUTH_MODE": "dev",
    "LEDGER_DATABASE_URL": "postgresql+asyncpg://sb_app:x@h/ledger",
}
SB_OBS_HANDLER = "sb_obs.structlog"


class ScriptedRelay:
    """Returns the scripted `run_once` results in order; a PublishFailed entry is raised."""

    def __init__(
        self, results: list[int | PublishFailed], stop_when_done: asyncio.Event | None = None
    ) -> None:
        self.results, self.stop_when_done, self.runs = results, stop_when_done, 0

    async def run_once(self) -> int:
        self.runs += 1
        result = self.results.pop(0)
        if not self.results and self.stop_when_done is not None:
            self.stop_when_done.set()
        if isinstance(result, PublishFailed):
            raise result
        return result


async def test_the_loop_runs_until_stop_is_set() -> None:
    stop = asyncio.Event()
    relay = ScriptedRelay([3, 1, 0], stop)
    await asyncio.wait_for(relay_loop(relay, stop), timeout=5)
    assert relay.runs == 3


async def test_a_busy_relay_runs_again_without_waiting() -> None:
    stop = asyncio.Event()
    relay = ScriptedRelay([5, 5, 5, 5], stop)
    # Four busy runs well inside the 1 s idle wait: a published batch is followed immediately.
    await asyncio.wait_for(relay_loop(relay, stop), timeout=0.5)
    assert relay.runs == 4


async def test_an_idle_relay_wakes_as_soon_as_stop_is_set() -> None:
    stop = asyncio.Event()
    relay = ScriptedRelay([0])  # idle; stop is set from outside below
    looping = asyncio.create_task(relay_loop(relay, stop))
    async with asyncio.timeout(1):
        while relay.runs < 1:  # yield until the loop has run once and is in its idle wait
            await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(looping, timeout=0.5)  # not after the full 1 s idle wait
    assert relay.runs == 1


async def test_a_fatal_publish_failure_propagates() -> None:
    stop = asyncio.Event()
    relay = ScriptedRelay([2, PublishFailed("fenced", fatal=True)], stop)
    with pytest.raises(PublishFailed, match="fenced"):
        await asyncio.wait_for(relay_loop(relay, stop), timeout=5)


def test_importing_the_consumer_builds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LEDGER_* settings exist here, so importing would fail if it built the container."""
    for name in [n for n in os.environ if n.startswith("LEDGER_")]:
        monkeypatch.delenv(name)
    monkeypatch.delitem(sys.modules, "ledger.consumer", raising=False)
    module = importlib.import_module("ledger.consumer")
    assert callable(module.main)


@pytest.fixture
def clean_root_logger() -> Iterator[logging.Logger]:
    """Restore the root logger afterwards; start without sb_obs's handler."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    for h in [h for h in root.handlers if h.get_name() == SB_OBS_HANDLER]:
        root.removeHandler(h)
    try:
        yield root
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.reset_defaults()  # drop the config bound to capsys's stream


def test_a_failed_task_logs_one_exit_event_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch,
    clean_root_logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit-to-restart (D12): the supervisor sees exit code 1 and one structured log event."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    async def failing_run(_: Settings) -> None:
        raise ExceptionGroup("tasks", [PublishFailed("producer fenced", fatal=True)])

    monkeypatch.setattr(ledger.consumer, "run", failing_run)
    with pytest.raises(SystemExit) as exited:
        ledger.consumer.main()
    assert exited.value.code == 1
    records = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    exits = [r for r in records if r["event"] == "ledger.consumer.exited"]
    assert len(exits) == 1
    assert exits[0]["errors"] == ["PublishFailed: producer fenced"]

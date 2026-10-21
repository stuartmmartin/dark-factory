"""Every event the ledger emits has a contract file (D12).

kafka-init creates topics only from `contracts/events/*.json` and compose has auto-create off,
so a missing file stalls the relay on the event's first row. The testcontainers broker
auto-creates topics, so only this test catches it before compose does.
"""

import inspect
from pathlib import Path

import pytest

from ledger.domain import events
from sb_kernel.events import DomainEvent

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts" / "events"
EMITTED = [
    cls
    for _, cls in inspect.getmembers(events, inspect.isclass)
    if issubclass(cls, DomainEvent)
    and cls is not DomainEvent
    and cls.__module__ == events.__name__
    and not inspect.isabstract(cls)
]


def test_the_ledger_defines_at_least_one_event() -> None:
    assert EMITTED  # guards the parametrized test below against an empty discovery


@pytest.mark.parametrize("event", EMITTED, ids=lambda cls: cls.topic())
def test_every_emitted_event_has_a_contract_file(event: type[DomainEvent]) -> None:
    assert (CONTRACTS / f"{event.topic()}.json").is_file()

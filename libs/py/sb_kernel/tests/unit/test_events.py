from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from sb_kernel.events import DomainEvent


class ThingHappened(DomainEvent):
    event_type = "demo.thing.happened"
    schema_version = 2
    thing_id: UUID

    def event_key(self) -> str:
        return str(self.thing_id)


def test_topic_and_key() -> None:
    event = ThingHappened(thing_id=uuid4())
    assert ThingHappened.topic() == "demo.thing.happened.v2"
    assert event.event_key() == str(event.thing_id)


def test_events_are_frozen() -> None:
    event = ThingHappened(thing_id=uuid4())
    with pytest.raises(ValidationError):
        event.thing_id = uuid4()  # type: ignore[misc]  # asserting immutability


def test_abstract_event_cannot_be_instantiated() -> None:
    class Incomplete(DomainEvent):
        event_type = "demo.incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # pyright: ignore[reportAbstractUsage]  # asserting the rejection

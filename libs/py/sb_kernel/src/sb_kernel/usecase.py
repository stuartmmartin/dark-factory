"""The use case protocol (A4): one async __call__ from a command to a result."""

from typing import Protocol


class UseCase[C, R](Protocol):
    async def __call__(self, command: C, /) -> R: ...

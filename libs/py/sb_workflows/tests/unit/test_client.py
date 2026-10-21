import socket
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

import pytest
from temporalio.client import Client
from temporalio.service import TLSConfig

from sb_workflows.client import connect


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _silent_listener() -> Iterator[int]:
    """Accepts TCP connections in the kernel backlog but never speaks: the handshake hangs."""
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(8)
        yield int(s.getsockname()[1])


async def test_connect_to_closed_port_fails_fast() -> None:
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="Failed client connect"):
        await connect(f"127.0.0.1:{_closed_port()}", connect_timeout_s=0.5)
    assert time.monotonic() - start < 2


async def test_connect_times_out_naming_the_target() -> None:
    with _silent_listener() as port:
        target = f"127.0.0.1:{port}"
        start = time.monotonic()
        with pytest.raises(TimeoutError, match=target):
            await connect(target, connect_timeout_s=0.5)
        assert time.monotonic() - start < 2


class _RecordingConnect:
    """Stands in for `Client.connect`: records the keyword arguments it was given."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, target: str, **kwargs: Any) -> str:
        self.calls.append({"target": target, **kwargs})
        return "client"


async def test_connect_passes_tls_and_api_key_through(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = _RecordingConnect()
    monkeypatch.setattr(Client, "connect", recording)
    tls = TLSConfig(domain="temporal.internal")
    await connect("t:7233", namespace="ns", tls=tls, api_key="k-123")
    [call] = recording.calls
    assert (call["target"], call["namespace"], call["tls"], call["api_key"]) == (
        "t:7233",
        "ns",
        tls,
        "k-123",
    )


async def test_connect_defaults_to_plaintext_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingConnect()
    monkeypatch.setattr(Client, "connect", recording)
    await connect("t:7233")
    [call] = recording.calls
    assert (call["tls"], call["api_key"]) == (False, None)

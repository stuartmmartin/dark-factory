"""`ledger-cli` end to end: the real HTTP transport against the real API on a loopback port.

The API runs under uvicorn in a background thread (its own event loop and engine) on the
migrated `ledger_test` database; the CLI talks to it exactly as a user's shell would.
"""

import socket
import threading
from collections.abc import Iterator
from uuid import uuid4

import pytest
import uvicorn

from ledger.bootstrap import build_api
from ledger.client.cli import main
from ledger.client.http import UrllibTransport
from ledger.infrastructure.settings import Settings


@pytest.fixture(scope="module")
def api_url(ledger_settings: Settings) -> Iterator[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(build_api(ledger_settings), log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:  # uvicorn flips this once it is accepting connections
        thread.join(timeout=0.05)
        assert thread.is_alive(), "uvicorn exited during startup"
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_open_transfer_and_read_balances(api_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    transport = UrllibTransport(api_url, timeout_seconds=10)
    tenant = ["--tenant", str(uuid4())]

    def cli(*argv: str) -> int:
        return main([*tenant, *argv], transport=transport)

    assert cli("open", "Operating cash") == 0
    assert cli("open", "Savings") == 0
    assert cli("open", "Owner equity") == 0
    assert cli("transfer", "1000.00", "--from", "Owner equity", "--to", "Operating cash") == 0
    assert cli("transfer", "250", "--from", "Operating cash", "--to", "Savings") == 0
    capsys.readouterr()

    assert cli("accounts") == 0
    _, *rows = capsys.readouterr().out.splitlines()
    # NAME (may contain spaces), CURRENCY, BALANCE, ID
    balances = {name: (ccy, bal) for name, ccy, bal, _ in (r.rsplit(maxsplit=3) for r in rows)}
    assert balances == {
        "Operating cash": ("USD", "750.00"),
        "Savings": ("USD", "250.00"),
        "Owner equity": ("USD", "-1000.00"),
    }

    assert cli("post", "Unbalanced", "debit:Savings:1.00", "credit:Owner equity:0.99") == 1
    assert "does not balance" in capsys.readouterr().err

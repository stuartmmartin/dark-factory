"""`UrllibTransport` against real loopback sockets: every way a reply can go wrong (T9)."""

import socket
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ledger.client.http import Reply, TransportError, UrllibTransport

Answer = tuple[int, bytes]


@pytest.fixture
def serve() -> Iterator[Callable[[Answer], str]]:
    """`serve((status, body))` starts a one-route server on loopback and returns its URL."""
    servers: list[HTTPServer] = []

    def start(answer: Answer) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = answer
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - base name
                """Silenced, to keep test output clean."""

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _get(url: str, timeout: float = 5) -> Reply:
    return UrllibTransport(url, timeout_seconds=timeout)("GET", "/x", body=None, headers={})


def test_a_json_reply_is_returned(serve: Callable[[Answer], str]) -> None:
    assert _get(serve((200, b'{"ok": true}'))) == Reply(200, {"ok": True})


def test_a_json_error_reply_is_returned_not_raised(serve: Callable[[Answer], str]) -> None:
    reply = _get(serve((422, b'{"code": "validation_failed", "detail": "no"}')))
    assert reply == Reply(422, {"code": "validation_failed", "detail": "no"})


def test_a_non_json_error_reply_becomes_a_problem(serve: Callable[[Answer], str]) -> None:
    reply = _get(serve((502, b"Bad Gateway")))
    assert reply == Reply(502, {"code": "http_error", "detail": "Bad Gateway"})


def test_a_non_json_success_reply_is_a_transport_error(serve: Callable[[Answer], str]) -> None:
    with pytest.raises(TransportError, match="invalid JSON"):
        _get(serve((200, b"<html>")))


def test_a_closed_port_is_a_transport_error() -> None:
    with socket.socket() as sock:  # bind then close: nothing listens on this port any more
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(TransportError, match="cannot reach the ledger"):
        _get(f"http://127.0.0.1:{port}")


def test_a_silent_server_times_out_as_a_transport_error() -> None:
    with socket.socket() as sock:  # accepts the connection (backlog) but never answers
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        with pytest.raises(TransportError, match="cannot reach the ledger"):
            _get(f"http://127.0.0.1:{sock.getsockname()[1]}", timeout=0.1)


def test_a_non_http_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="http"):
        UrllibTransport("ftp://example.test", timeout_seconds=1)

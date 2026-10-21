import socket

import pytest

from sb_testing.network import ORIGINAL_CONNECT, NetworkForbidden, is_loopback_host


def test_external_connections_are_blocked_by_default() -> None:
    # NetworkForbidden is deliberately not OSError; create_connection only closes on OSError.
    # Own the test socket explicitly so the intentionally rejected connection cannot leak it.
    with socket.socket() as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkForbidden, match="allow_network"):
            sock.connect(("93.184.216.34", 80))


def test_loopback_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


@pytest.mark.allow_network
def test_marker_disables_the_guard() -> None:
    assert socket.socket.connect is ORIGINAL_CONNECT


def test_external_ipv6_is_blocked() -> None:
    with (
        socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkForbidden),
    ):
        sock.connect(("2001:4860:4860::8888", 80))


def test_connect_ex_is_guarded_too() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkForbidden),
    ):
        sock.connect_ex(("93.184.216.34", 80))


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.5.6.7", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("localhost", True),
        ("0.0.0.0", True),  # noqa: S104 - classification under test, not a bind
        ("93.184.216.34", False),
        ("2001:4860:4860::8888", False),
        ("::ffff:8.8.8.8", False),
        ("example.com", False),
    ],
)
def test_loopback_classification(host: str, expected: bool) -> None:
    assert is_loopback_host(host) is expected

"""Hermetic tests (T10): block non-loopback network connections unless explicitly allowed.

Scope: this guards Python `socket.socket.connect` / `connect_ex` for AF_INET and AF_INET6 only.
It does NOT guard native clients that open their own sockets (librdkafka in confluent-kafka,
libpq), DNS lookups, or UDP `sendto`. Those need real isolation (containers on loopback).
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest

ORIGINAL_CONNECT = socket.socket.connect
ORIGINAL_CONNECT_EX = socket.socket.connect_ex


def is_loopback_host(host: str | None) -> bool:
    """True for localhost, 127.0.0.0/8, ::1, ::ffff:127.x and the unspecified address."""
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host.partition("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback or addr.is_unspecified


class NetworkForbidden(RuntimeError):  # noqa: N818 - name fixed by the plan interface
    """A test tried to reach the network."""


def _host(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])  # pyright: ignore[reportUnknownArgumentType]
    return None


def guard(monkeypatch: pytest.MonkeyPatch) -> None:
    def check(sock: socket.socket, address: Any) -> None:
        host = _host(address)
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback_host(host):
            raise NetworkForbidden(
                f"test tried to connect to {host!r}; tests are hermetic (T10). "
                "Use a fake, or mark the test @pytest.mark.allow_network with a reason."
            )

    def connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        ORIGINAL_CONNECT(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return ORIGINAL_CONNECT_EX(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)

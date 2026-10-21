import socket

import pytest

from sb_testing.network import ORIGINAL_CONNECT

pytestmark = pytest.mark.allow_network


def test_module_level_marker_disables_the_guard() -> None:
    assert socket.socket.connect is ORIGINAL_CONNECT

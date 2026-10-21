import pytest

from sb_checks.checks.httpx_timeout import HttpxTimeoutCheck

SRC = "services/ledger/src/ledger/infrastructure/fx_client.py"


@pytest.mark.parametrize(
    "call",
    [
        "httpx.get(url)",
        "httpx.post(url, json={})",
        "httpx.AsyncClient()",
        "httpx.Client(base_url=u)",
    ],
)
def test_flags_httpx_calls_without_timeout(run_check, call: str) -> None:
    [v] = run_check(HttpxTimeoutCheck(), SRC, f"import httpx\n{call}\n")
    assert v.check_id == "httpx-timeout"


@pytest.mark.parametrize(
    "call", ["httpx.get(url, timeout=5)", "httpx.AsyncClient(timeout=httpx.Timeout(5.0))"]
)
def test_explicit_timeout_is_fine(run_check, call: str) -> None:
    assert run_check(HttpxTimeoutCheck(), SRC, f"import httpx\n{call}\n") == []


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param("import httpx as hx\nhx.get(url)\n", "httpx.get()", id="module-alias"),
        pytest.param(
            "from httpx import AsyncClient\nAsyncClient()\n", "httpx.AsyncClient()", id="from"
        ),
        pytest.param(
            "from httpx import Client as C\nC(base_url=u)\n", "httpx.Client()", id="from-as"
        ),
        pytest.param("from httpx import get\nget(url)\n", "httpx.get()", id="from-function"),
    ],
)
def test_flags_aliased_and_from_imported_calls(run_check, source: str, message: str) -> None:
    [v] = run_check(HttpxTimeoutCheck(), SRC, source)
    assert v.message == f"{message} without timeout="


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import httpx as hx\nhx.get(url, timeout=5)\n", id="alias-with-timeout"),
        pytest.param("from httpx import Client\nClient(timeout=5)\n", id="from-with-timeout"),
        pytest.param("from requests import get\nget(url)\n", id="other-library"),
        pytest.param("from httpx import Timeout\nTimeout(5.0)\n", id="not-a-call-we-police"),
    ],
)
def test_aliases_with_timeout_or_other_libraries_are_fine(run_check, source: str) -> None:
    assert run_check(HttpxTimeoutCheck(), SRC, source) == []


class TestDocumentedBlindSpots:
    def test_kwargs_expansion_is_trusted(self, run_check) -> None:
        assert run_check(HttpxTimeoutCheck(), SRC, "import httpx\nhttpx.get(url, **opts)\n") == []

    def test_client_instance_methods_are_not_checked(self, run_check) -> None:
        # Mitigation: the client constructor itself must carry timeout=.
        assert run_check(HttpxTimeoutCheck(), SRC, "client.get(url)\n") == []

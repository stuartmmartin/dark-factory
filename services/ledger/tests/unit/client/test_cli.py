"""`ledger-cli` against an in-memory fake of the ledger HTTP API (T3: a fake, not a mock).

The fake keeps accounts and balances, so the tests check what the user sees (stdout, exit code)
and what the API ends up holding, not which calls were made.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from ledger.client.cli import main
from ledger.client.http import Reply, TransportError

TENANT = "00000000-0000-0000-0000-0000000000d3"


@dataclass
class FakeLedgerApi:
    """Enough of /v1 to drive the client: accounts, balances and balanced entries."""

    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    balances: dict[str, Decimal] = field(default_factory=dict)
    headers_seen: list[dict[str, str]] = field(default_factory=list)

    def __call__(
        self, method: str, path: str, *, body: dict[str, Any] | None, headers: dict[str, str]
    ) -> Reply:
        self.headers_seen.append(headers)
        match method, path.split("?", maxsplit=1)[0].strip("/").split("/"):
            case "POST", ["v1", "accounts"]:
                assert body is not None
                account_id = str(uuid4())
                self.accounts[account_id] = {"id": account_id, **body, "opened_at": "2026-01-01"}
                self.balances[account_id] = Decimal(0)
                return Reply(201, self.accounts[account_id])
            case "GET", ["v1", "accounts"]:
                return Reply(200, {"items": list(self.accounts.values())})
            case "GET", ["v1", "accounts", account_id, "balance"]:
                if account_id not in self.accounts:
                    return Reply(404, {"code": "not_found", "detail": "account not found"})
                balance = self.balances[account_id]
                return Reply(
                    200,
                    {
                        "account_id": account_id,
                        "currency": self.accounts[account_id]["currency"],
                        "debits": "0.00",
                        "credits": "0.00",
                        "balance": f"{balance:.2f}",
                    },
                )
            case "POST", ["v1", "journal-entries"]:
                assert body is not None
                signed = [
                    (ln["account_id"], Decimal(ln["amount"]) * (1 if ln["side"] == "debit" else -1))
                    for ln in body["lines"]
                ]
                if sum(amount for _, amount in signed) != 0:
                    return Reply(422, {"code": "validation_failed", "detail": "does not balance"})
                for account_id, amount in signed:
                    self.balances[account_id] += amount
                return Reply(201, {"id": str(UUID(int=7)), **body, "currency": "USD"})
            case _:
                raise AssertionError(f"unexpected request {method} {path}")


@pytest.fixture
def api() -> FakeLedgerApi:
    return FakeLedgerApi()


def run(api: FakeLedgerApi, *argv: str) -> int:
    return main(list(argv), transport=api)


def balance_of(api: FakeLedgerApi, name: str) -> Decimal:
    (account_id,) = [i for i, a in api.accounts.items() if a["name"] == name]
    return api.balances[account_id]


def test_open_creates_an_account_and_prints_its_id(api: FakeLedgerApi, capsys) -> None:
    assert run(api, "open", "Operating cash", "--currency", "usd") == 0
    (account,) = api.accounts.values()
    assert (account["name"], account["currency"]) == ("Operating cash", "USD")
    assert account["id"] in capsys.readouterr().out


def test_every_request_carries_the_tenant(api: FakeLedgerApi) -> None:
    run(api, "--tenant", TENANT, "accounts")
    assert api.headers_seen[0]["X-Tenant-Id"] == TENANT


def test_transfer_debits_the_destination_and_credits_the_source(api: FakeLedgerApi, capsys) -> None:
    run(api, "open", "Operating cash")
    run(api, "open", "Savings")
    assert run(api, "transfer", "250.00", "--from", "Operating cash", "--to", "Savings") == 0
    assert balance_of(api, "Savings") == Decimal("250.00")
    assert balance_of(api, "Operating cash") == Decimal("-250.00")
    assert "posted" in capsys.readouterr().out


def test_post_accepts_side_account_amount_lines(api: FakeLedgerApi) -> None:
    run(api, "open", "Cash")
    run(api, "open", "Rent")
    run(api, "open", "Utilities")
    code = run(
        api,
        "post",
        "March bills",
        "debit:Rent:1200.00",
        "debit:Utilities:150",
        "credit:Cash:1350.00",
    )
    assert code == 0
    assert balance_of(api, "Rent") == Decimal("1200.00")
    assert balance_of(api, "Cash") == Decimal("-1350.00")


def test_accounts_lists_names_currencies_and_balances(api: FakeLedgerApi, capsys) -> None:
    run(api, "open", "Cash")
    run(api, "open", "Equity")
    run(api, "transfer", "10", "--from", "Equity", "--to", "Cash")
    capsys.readouterr()
    assert run(api, "accounts") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["NAME", "CURRENCY", "BALANCE", "ID"]
    assert out[1].split()[:3] == ["Cash", "USD", "10.00"]
    assert out[2].split()[:3] == ["Equity", "USD", "-10.00"]


def test_balance_accepts_a_name_or_an_id(api: FakeLedgerApi, capsys) -> None:
    run(api, "open", "Cash")
    (account_id,) = api.accounts
    capsys.readouterr()
    assert run(api, "balance", "Cash") == 0
    assert run(api, "balance", account_id) == 0
    assert capsys.readouterr().out.count("balance") == 2


def test_an_api_error_prints_its_code_and_detail_and_exits_1(api: FakeLedgerApi, capsys) -> None:
    run(api, "open", "Cash")
    run(api, "open", "Equity")
    code = run(api, "post", "Oops", "debit:Cash:10", "credit:Equity:9")
    assert code == 1
    assert "validation_failed: does not balance" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["Nope", "Cash"], ids=["unknown", "ambiguous"])
def test_an_unknown_or_ambiguous_account_name_exits_1(api: FakeLedgerApi, capsys, name) -> None:
    run(api, "open", "Cash")
    run(api, "open", "Cash")
    run(api, "open", "Equity")
    assert run(api, "transfer", "1", "--from", name, "--to", "Equity") == 1
    assert "account" in capsys.readouterr().err


@pytest.mark.parametrize("line", ["debit:Cash", "loan:Cash:1", "debit::1"])
def test_a_malformed_line_is_a_usage_error(api: FakeLedgerApi, line: str) -> None:
    with pytest.raises(SystemExit) as exit_:
        run(api, "post", "Bad", line, "credit:Cash:1")
    assert exit_.value.code == 2


def test_a_url_without_http_is_a_usage_error(api: FakeLedgerApi, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        run(api, "--url", "localhost:8001", "accounts")
    assert exit_.value.code == 2
    assert "http" in capsys.readouterr().err


def test_a_full_account_page_says_the_list_may_be_truncated(api: FakeLedgerApi, capsys) -> None:
    for n in range(200):
        api.accounts[str(n)] = {"id": str(n), "name": f"A{n}", "currency": "USD"}
        api.balances[str(n)] = Decimal(0)
    assert run(api, "accounts") == 0
    assert "first 200 accounts" in capsys.readouterr().err


def test_an_unreachable_service_exits_2(capsys) -> None:
    def down(method: str, path: str, *, body: object, headers: object) -> Reply:
        raise TransportError("connection refused")

    assert main(["accounts"], transport=down) == 2
    out, err = capsys.readouterr()
    assert "connection refused" in err
    assert out == ""  # no half-printed table

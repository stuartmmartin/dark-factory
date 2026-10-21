"""`ledger-cli`: open accounts, post balanced entries and read balances over the ledger API.

    ledger-cli open "Operating cash" --currency USD
    ledger-cli transfer 250.00 --from "Operating cash" --to Savings
    ledger-cli post "March bills" debit:Rent:1200.00 credit:"Operating cash":1200.00
    ledger-cli accounts
    ledger-cli balance Savings

Accounts are named by id or by exact name. Amounts are decimal strings; the API does every
check (balance, precision, currency), and its errors are printed as `error: <code>: <detail>`.
Exit codes: 0 success, 1 the API refused the request, 2 usage error or the API is unreachable.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from ledger.client.http import Reply, Transport, TransportError, UrllibTransport
from ledger.client.settings import ClientSettings

SIDES = ("debit", "credit")
PAGE = 200  # the API's largest `limit`


class ApiError(Exception):
    """The API answered with an error (or the request named an account that does not exist)."""


class Ledger:
    """The ledger API as plain method calls, for one tenant."""

    def __init__(self, transport: Transport, tenant: str) -> None:
        self._transport, self._headers = transport, {"X-Tenant-Id": tenant, "X-Actor": "ledger-cli"}

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = dict(self._headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        reply: Reply = self._transport(method, path, body=body, headers=headers)
        if reply.status >= 400:  # noqa: PLR2004 - HTTP error statuses
            problem = reply.body if isinstance(reply.body, dict) else {}
            code, detail = problem.get("code", reply.status), problem.get("detail", "")
            raise ApiError(f"{code}: {detail}")
        return reply.body

    def open_account(self, name: str, currency: str, key: str | None) -> dict[str, Any]:
        return self._call("POST", "/v1/accounts", {"name": name, "currency": currency}, key)

    def accounts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = self._call("GET", f"/v1/accounts?limit={PAGE}")["items"]
        if len(items) == PAGE:  # the API has no paging yet: say so rather than drop silently
            print(f"warning: showing the first {PAGE} accounts only", file=sys.stderr)
        return items

    def balance(self, account_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/accounts/{account_id}/balance")

    def post(
        self, description: str, lines: list[tuple[str, str, str]], key: str | None
    ) -> dict[str, Any]:
        """`lines` are (side, account id or name, amount)."""
        body = {
            "description": description,
            "lines": [
                {"account_id": self.resolve(account), "side": side, "amount": amount}
                for side, account, amount in lines
            ],
        }
        return self._call("POST", "/v1/journal-entries", body, key)

    def resolve(self, account: str) -> str:
        """An account id as given, or the id of the one account with exactly this name."""
        try:
            return str(UUID(account))
        except ValueError:
            pass
        matches = [a["id"] for a in self.accounts() if a["name"] == account]
        if len(matches) != 1:
            found = "no account" if not matches else f"{len(matches)} accounts"
            raise ApiError(f"{found} named {account!r}; use the account id instead")
        return matches[0]


def _line(text: str) -> tuple[str, str, str]:
    """`side:account:amount`; the account (a name may contain ':') is everything in between."""
    side, _, rest = text.partition(":")
    account, _, amount = rest.rpartition(":")
    if side not in SIDES or not account or not amount:
        raise argparse.ArgumentTypeError(f"expected debit|credit:<account>:<amount>, got {text!r}")
    return side, account, amount


def _url(text: str) -> str:
    if not text.startswith(("http://", "https://")):
        raise argparse.ArgumentTypeError(f"expected an http(s) URL, got {text!r}")
    return text


def _parser(defaults: ClientSettings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger-cli", description="A command-line client of the ledger API."
    )
    parser.add_argument(
        "--url", default=defaults.url, type=_url, help="API base URL (LEDGER_CLI_URL)"
    )
    parser.add_argument(
        "--tenant",
        default=defaults.tenant,
        help="tenant id sent as X-Tenant-Id (LEDGER_CLI_TENANT)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    open_ = commands.add_parser("open", help="open an account")
    open_.add_argument("name")
    open_.add_argument("--currency", default="USD", type=str.upper)
    open_.add_argument("--idempotency-key")

    commands.add_parser("accounts", help="list accounts with their balances")

    balance = commands.add_parser("balance", help="show one account's debits, credits, balance")
    balance.add_argument("account", help="account id or exact name")

    transfer = commands.add_parser("transfer", help="move an amount from one account to another")
    transfer.add_argument("amount")
    transfer.add_argument("--from", dest="source", required=True, help="credited account")
    transfer.add_argument("--to", dest="destination", required=True, help="debited account")
    transfer.add_argument("--description", default="Transfer")
    transfer.add_argument("--idempotency-key")

    post = commands.add_parser("post", help="post a journal entry of two or more lines")
    post.add_argument("description")
    post.add_argument("lines", nargs="+", type=_line, metavar="debit|credit:ACCOUNT:AMOUNT")
    post.add_argument("--idempotency-key")
    return parser


def _print_entry(entry: dict[str, Any], names: dict[str, str]) -> None:
    print(f"posted {entry['id']}: {entry['description']} ({entry['currency']})")
    for line in entry["lines"]:
        account = names.get(line["account_id"], line["account_id"])
        print(f"  {line['side']:<6} {line['amount']:>14}  {account}")


def _run(args: argparse.Namespace, ledger: Ledger) -> None:
    match args.command:
        case "open":
            account = ledger.open_account(args.name, args.currency, args.idempotency_key)
            print(f"opened {account['name']} ({account['currency']}) {account['id']}")
        case "accounts":
            rows = [  # fetched before printing, so a failure prints no half table
                (a["name"], a["currency"], ledger.balance(a["id"])["balance"], a["id"])
                for a in ledger.accounts()
            ]
            print(f"{'NAME':<24} {'CURRENCY':<8} {'BALANCE':>14}  ID")
            for name, currency, balance, account_id in rows:
                print(f"{name:<24} {currency:<8} {balance:>14}  {account_id}")
        case "balance":
            result = ledger.balance(ledger.resolve(args.account))
            for key in ("debits", "credits", "balance"):
                print(f"{key:<8} {result[key]:>14} {result['currency']}")
        case _:  # "transfer" or "post": argparse allows no other command
            lines = (
                [("debit", args.destination, args.amount), ("credit", args.source, args.amount)]
                if args.command == "transfer"
                else args.lines
            )
            entry = ledger.post(args.description, lines, args.idempotency_key)
            _print_entry(entry, {a["id"]: a["name"] for a in ledger.accounts()})


def main(argv: Sequence[str] | None = None, transport: Transport | None = None) -> int:
    settings = ClientSettings()
    args = _parser(settings).parse_args(argv)
    ledger = Ledger(transport or UrllibTransport(args.url, settings.timeout_seconds), args.tenant)
    try:
        _run(args, ledger)
    except ApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except TransportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def entrypoint() -> None:
    """The `ledger-cli` console script."""
    sys.exit(main())

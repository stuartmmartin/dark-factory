"""The ledger's HTTP routes: each resolves its use case from the container and does nothing else
(A8). Errors map to problem+json once, in `sb_http.errors`.

The function names are the OpenAPI operationIds (D2) and part of the committed contract
(`contracts/openapi/ledger.json`): renaming one is an API change.
"""

from __future__ import annotations

from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from ledger.application.dto import (
    GetAccountBalanceQuery,
    GetAccountQuery,
    ListAccountsQuery,
    OpenAccountCommand,
    PostJournalEntryCommand,
)
from ledger.application.use_cases.get_account import GetAccount
from ledger.application.use_cases.get_account_balance import GetAccountBalance
from ledger.application.use_cases.list_accounts import MAX_LIMIT, ListAccounts
from ledger.application.use_cases.open_account import OpenAccount
from ledger.application.use_cases.post_journal_entry import PostJournalEntry
from ledger.interface.http.schemas import (
    AccountIn,
    AccountListOut,
    AccountOut,
    BalanceOut,
    JournalEntryIn,
    JournalEntryOut,
)
from sb_http import idempotency

router = APIRouter(prefix="/v1")


class _UseCases(Protocol):
    """What the routes need from `ledger.bootstrap.Container` (interface cannot import it)."""

    @property
    def open_account(self) -> OpenAccount: ...
    @property
    def get_account(self) -> GetAccount: ...
    @property
    def list_accounts(self) -> ListAccounts: ...
    @property
    def post_journal_entry(self) -> PostJournalEntry: ...
    @property
    def get_account_balance(self) -> GetAccountBalance: ...


def _use_cases(request: Request) -> _UseCases:
    return cast(_UseCases, request.app.state.container)


@router.post(
    "/accounts",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": AccountOut, "description": "Idempotent replay"}},
)
async def open_account(
    body: AccountIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Depends(idempotency.idempotency_key)],
) -> AccountOut:
    """Open an account (201). A replayed `Idempotency-Key` returns the original account (200)."""
    result = await _use_cases(request).open_account(
        OpenAccountCommand(name=body.name, currency=body.currency, idempotency_key=idempotency_key)
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return AccountOut.of(result)


@router.get("/accounts")
async def list_accounts(
    request: Request, limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100
) -> AccountListOut:
    """The caller's accounts, oldest first, at most `limit` (1-200, default 100)."""
    return AccountListOut.of(
        await _use_cases(request).list_accounts(ListAccountsQuery(limit=limit))
    )


@router.get("/accounts/{account_id}")
async def get_account(account_id: UUID, request: Request) -> AccountOut:
    """Read one account of the caller's tenant; another tenant's reads as 404."""
    return AccountOut.of(
        await _use_cases(request).get_account(GetAccountQuery(account_id=account_id))
    )


@router.get("/accounts/{account_id}/balance")
async def get_account_balance(account_id: UUID, request: Request) -> BalanceOut:
    """Debits, credits and balance (debits minus credits); another tenant's account is 404."""
    return BalanceOut.of(
        await _use_cases(request).get_account_balance(GetAccountBalanceQuery(account_id=account_id))
    )


@router.post(
    "/journal-entries",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": JournalEntryOut, "description": "Idempotent replay"}},
)
async def post_journal_entry(
    body: JournalEntryIn,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Depends(idempotency.idempotency_key)],
) -> JournalEntryOut:
    """Post a balanced entry (201): debits must equal credits, all accounts in one currency.
    A replayed `Idempotency-Key` returns the original entry (200)."""
    result = await _use_cases(request).post_journal_entry(
        PostJournalEntryCommand(
            description=body.description,
            lines=tuple(line.command() for line in body.lines),
            idempotency_key=idempotency_key,
        )
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return JournalEntryOut.of(result)

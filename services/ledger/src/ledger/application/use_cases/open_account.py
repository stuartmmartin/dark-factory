"""Open an account for the current tenant.

Business rules:
    R1: The currency must be a supported ISO 4217 code and the name 1-200 non-blank
        characters; otherwise ValidationFailed and nothing is written.
    R2: Opening an account writes the account, one audit event and AccountOpened in the same
        transaction.
    R3: Repeating an idempotency key with the same request after the first has committed
        returns the original result flagged `replayed` and writes nothing; the same key with a
        different request is IdempotencyKeyReused (422); a duplicate racing the first (same
        key and request, before it commits) is a Conflict (409).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from ledger.application.dto import AccountResult, OpenAccountCommand, request_hash, to_result
from ledger.application.ports import UowFactory
from ledger.domain.accounts import Account
from ledger.domain.events import AccountOpened
from sb_kernel.clock import Clock
from sb_kernel.context import current_context
from sb_kernel.errors import IdempotencyKeyReused
from sb_kernel.ids import new_id as default_new_id
from sb_kernel.money import Currency


class OpenAccount:
    def __init__(
        self, uow: UowFactory, clock: Clock, new_id: Callable[[], UUID] = default_new_id
    ) -> None:
        self._uow, self._clock, self._new_id = uow, clock, new_id

    async def __call__(self, command: OpenAccountCommand) -> AccountResult:
        fingerprint = request_hash(command)
        async with self._uow() as uow:
            if command.idempotency_key is not None:  # R3: a sequential replay writes nothing
                stored = await uow.idempotency.get(command.idempotency_key)
                if stored is not None:
                    if stored.request_hash != fingerprint:
                        raise IdempotencyKeyReused(
                            "idempotency key already used for a different request"
                        )
                    return AccountResult.model_validate({**stored.response, "replayed": True})
            account = Account(  # R1: Currency.of and the entity invariants raise ValidationFailed
                id=self._new_id(),
                tenant_id=current_context().tenant_id,
                name=command.name,
                currency=Currency.of(command.currency),
                opened_at=self._clock.now(),
            )
            await uow.accounts.add(account)  # R2: account, audit and event in one transaction
            result = to_result(account)
            # The replay body keeps the name: idempotency_keys rows are mutable (erasable).
            stored_body = result.model_dump(mode="json", exclude={"replayed"})
            uow.audit.record(  # no name: the audit chain is append-only, so no free-text PII
                action="account.open",
                entity_type="account",
                entity_id=str(account.id),
                before=None,
                after={
                    "id": account.id,
                    "currency": account.currency.code,
                    "opened_at": account.opened_at,
                },
            )
            uow.outbox.add(AccountOpened(account_id=account.id, currency=account.currency.code))
            if command.idempotency_key is not None:  # R3: a racing duplicate raises Conflict here
                await uow.idempotency.save(command.idempotency_key, fingerprint, stored_body)
            await uow.commit()
            return result

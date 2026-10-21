---
name: new-use-case
description: Add a use case to a service with make new-use-case — writes the one-class, one-__call__ module with its R<n> rule list and a RED test_R1_* over the service's fakes — then rules first, tests second, code last. Use for any new business operation.
---
# New use case
Reference: [add a use case](../../../docs/guides/add-a-use-case.md). Rules: A3, A4 (business
rules live in one use case file), T1 (test first), T2 (a test per rule), T3 (fakes), A13, A14.

1. `make new-use-case SVC=<service> NAME=<verb_noun>` (the module name, at most 32
   characters). It creates `src/<svc>/application/use_cases/<name>.py` (one class, one
   `__call__`, raising `NotImplementedError`) and `tests/unit/use_cases/test_<name>.py` with a
   `test_R1_<name>` that fails by design (T1). It refuses a bad or existing name.
2. **Rules first.** Replace `R1: <state the first business rule>` with the real rules, one
   `R<n>:` line each, in business words. A human verifies these lines, so each is one checkable
   sentence (what is allowed, what is refused and with which error, what is written).
3. **Tests second.** One `test_R<n>_*` per rule over the service's fakes
   (`tests/<svc>_fakes.py`, via the `uow` and `state` fixtures of `tests/unit/conftest.py`),
   asserting the rule's observable effect: committed state, audit records, outbox events, the
   error raised. Run `make test PKG=services/<svc>/tests/unit/use_cases/test_<name>.py` and see
   each fail for the right reason. `sb-checks` fails if a rule has no test or a test names a
   rule that does not exist.
4. **Code last.** Commands and results are frozen DTOs in `application/dto.py`. New ports go in
   `application/ports.py`, with a fake in `tests/<svc>_fakes.py` (staged until `commit()`) and a
   contract suite against the SQL adapter (T4). Use `Clock` for time (C4) and `Money` for
   amounts (C3).
5. **Writes** go through one `async with self._uow() as uow:` block that records the audit
   event (A14, no free-text PII in the payload), adds any event to `uow.outbox` (A11) and ends
   with `await uow.commit()`. Abort by raising an `sb_kernel.errors` error, never by returning
   early: when a consumer runs the use case on `sb_db.uow.joined(uow)`, `commit()` and
   `rollback()` are no-ops and only an exception undoes the work (see "Consumers that call
   a use case" in [the reference service's notes](../../../services/ledger/CLAUDE.md) and
   `services/ledger/src/ledger/interface/consumers/account_opened.py`). Type the factory as the service's `UowFactory` so a joined view is
   accepted.
6. **Idempotency** for a write a client or a retry may repeat: take `idempotency_key` in the
   command and follow `services/ledger/src/ledger/application/use_cases/open_account.py`
   (hash the command without its key, replay a stored response, `IdempotencyKeyReused` for a
   different request, `Conflict` for a racing duplicate).
7. Wire it: add it to the `Container` in `bootstrap.py`, and a thin route (A8) or handler that
   calls it and nothing else. After a route change run `make openapi`.

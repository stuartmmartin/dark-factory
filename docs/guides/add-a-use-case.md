# Add a use case

A use case is one business operation: one file in `application/use_cases/`, one class, one
`__call__`, and a docstring that lists its business rules as `R1:`, `R2:` lines. Each rule has a
`test_R<n>_*` test. Those two files are what a human reviewer reads. Agents follow the
[`new-use-case` skill](../../.claude/skills/new-use-case/SKILL.md); this is the human version.

## 1. Generate it

```sh
make new-use-case SVC=payments NAME=refund_payment
```

It creates `services/payments/src/payments/application/use_cases/refund_payment.py` (a
`RefundPayment` class that raises `NotImplementedError`) and
`services/payments/tests/unit/use_cases/test_refund_payment.py` with `test_R1_refund_payment`,
which fails on purpose: a test that has never failed proves nothing. It refuses a bad name, an
unknown service and an existing use case.

## 2. Write the rules

Replace `R1: <state the first business rule>` with the real rules, each one checkable sentence
in business words: what is allowed, what is refused (and with which error), what is written.
Changing a rule's meaning later is a decision for a human, not a refactor.

## 3. Write one failing test per rule

Each `test_R<n>_*` runs the use case over the in-memory fakes (`tests/<svc>_fakes.py`, through
the `uow` and `state` fixtures) and asserts what the rule promises: the committed state, the
audit record, the outbox event, or the error. Run it and check it fails for the right reason:

```sh
make test PKG=services/payments/tests/unit/use_cases/test_refund_payment.py
```

`sb-checks` (in `make check`) fails when a rule has no test, or a test names a rule the
docstring does not list.

## 4. Implement

- Commands and results are frozen DTOs in `application/dto.py`; a new port goes in
  `application/ports.py` with a fake and a contract suite against the SQL adapter.
- A write happens in one `async with self._uow() as uow:` block: the change, one audit record
  (no free-text personal data: the audit chain cannot be erased), any event on `uow.outbox`,
  then `await uow.commit()`.
- To refuse, raise an `sb_kernel.errors` error. Never return early to abort: a consumer runs
  the use case inside its own transaction, where only an exception undoes the work.
- If a client or a retry can send the same request twice, take an idempotency key and follow
  the reference service's `OpenAccount`
  (`services/ledger/src/ledger/application/use_cases/open_account.py`).
- Money is `sb_kernel.money.Money` (never float); time comes from the injected `Clock`.

Finally add the use case to the `Container` in `bootstrap.py` and give it a thin route or
handler that only calls it. After a route change run `make openapi` and commit the contract.

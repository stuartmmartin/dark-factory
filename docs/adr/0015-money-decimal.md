# ADR-0015: Money is Decimal + ISO currency; float banned in money paths

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
This is a financial ledger for a family office; a rounding error from binary floating-point
representation in a money calculation is not a cosmetic bug, it's a wrong balance. `float` cannot
represent most decimal fractions exactly (`0.1 + 0.2 != 0.3` in IEEE-754 binary), which is
unacceptable for `JournalEntry`/`Posting` amounts, the `allocate`/`balance` policies, and Postgres
storage of those values (spec §3's `sb_kernel` and §6.1's `Posting(account_id, amount: Money)` with
per-currency balancing to zero).

## Decision
Money is represented as `sb_kernel.Money`, a `Decimal` amount paired with an ISO 4217 currency
code, everywhere in domain and application code. Postgres stores money as `NUMERIC`, never
`float`/`double precision`. On the wire (HTTP JSON, event payloads), decimals are serialized as
**strings**, not JSON numbers, so no client-side float round-trip can reintroduce imprecision (spec
§6.4's pydantic schemas carry decimals as strings). `float(` and `: float` are banned by an
`sb-checks` AST rule in `domain/`, `application/`, and `sb_kernel.money` itself — enforced
mechanically, not left to review (spec §4.3).

## Consequences
Money math is exact and reviewable; the `allocate` policy's largest-remainder split can be tested
against precise invariants (parts sum exactly to the total, no part off by more than one minor
unit) rather than "close enough" floating-point assertions. The cost is that every number touching
money — inputs, arithmetic, currency-aware rounding to minor units, wire serialization — must go
through `Decimal` and `Money` deliberately; a naive `amount / 3` or a stray `float()` cast is a
real bug the AST check exists specifically to catch before it reaches review.

## Revisit when
A money path is found where the ban on `float` and the AST check produce a false positive that
can't be fixed by adjusting the code (only ever via a justified, individually-tracked allowlist
entry per spec §4.3, not by loosening the rule itself).

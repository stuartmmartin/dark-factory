# Ledger glossary

**Tenant** — a legal entity (person, trust, LLC, partnership) whose data is isolated by RLS.
_Avoid_: client, customer, family. _Invariant_: every ledger row belongs to exactly one tenant.

**Account** — a named bucket in one currency; the README and `ledger-cli` also call it a "ledger".
It has no type (asset, liability…), so its balance is signed. _Avoid_: wallet, position.
_Invariant_: the name is 1–200 non-blank characters; the currency is ISO 4217.

**Journal entry** — one dated, described movement of money: two or more lines whose debits equal
their credits, all in the accounts' one shared currency. Append-only: a mistake is corrected by a
new, reversing entry, never an edit. _Avoid_: transaction (ambiguous with the database's), transfer
(a transfer is just a two-line entry).

**Line** — one side of an entry: an account, `debit` or `credit`, and a positive amount within
the currency's minor units (more precision is rejected, never rounded).

**Balance** — an account's debits minus its credits (debit-positive). Money flowing into an
account (a debit) raises it; an account mostly credited (equity, income, a loan) is negative.

**Account count** — a per-tenant projection: how many `AccountOpened` events the tenant's consumer has applied.
It is derived and rebuildable from the events.

**Account count snapshot** — the account count recorded for a date by the snapshot workflow. A cache. The workflow keys each run on its workflow id, so re-running the same date replays the stored snapshot; start a new workflow id to refresh it.

**Allocation** — splitting an amount by weights so the parts sum exactly to the total (largest remainder).

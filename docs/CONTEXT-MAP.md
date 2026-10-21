# Context map

Bounded contexts that have a `CONTEXT.md` glossary, and how they relate.

| Context | Glossary | Publishes | Consumes |
|---|---|---|---|
| ledger | [services/ledger/CONTEXT.md](../services/ledger/CONTEXT.md) | `ledger.account.opened.v1` | `ledger.account.opened.v1` (reference consumer) |

Relationships: none yet. When a second context arrives, record here who is upstream, what
contract they share (`contracts/events`, `contracts/openapi`), and which words mean different
things on each side.

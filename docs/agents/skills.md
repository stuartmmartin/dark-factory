# Skills, agents, commands

| Skill | Use when |
|---|---|
| `tdd` | Writing any production code (T1) |
| `tighten` | Once per branch, before `/review`: simplify verbose code and wordy docs in the diff without changing behaviour |
| `code-review` | Once per branch, before it goes into `main` (PR marked ready, merge or push). It's a hard gate (see review-gates.md) |
| `spec` | Before non-trivial work: new use case, endpoint, event, workflow, schema change |
| `adversarial-rca` | Bugs and incidents whose cause isn't proven |
| `harvest` | Before review, when `.work/<slug>/` has working docs: move what lasts into tests, comments, `CLAUDE.md`, `CONTEXT.md`, ADRs or tickets |
| `security-review` | Auth, tenancy, endpoints, SQL, secrets, PII, CI, dependencies |
| `performance-review` | Slow paths, N+1s, heavy queries, locking migrations, consumer lag. Also the advisory `performance` focus in CI |
| `supply-chain-audit` | Dependency, Dockerfile or Actions changes, and CVEs |
| `alembic-migration` | Schema changes: tables, columns, indexes, RLS, append-only triggers |
| `kafka-event` | Publishing or consuming an event (outbox, inbox, JSON Schema contract) |
| `temporal-workflow` | Workflows and activities, deterministic ids, replay tests |
| `admin-acceptor` | Exposing a pure policy as a SQLAdmin acceptor |
| `new-service` | A new bounded context: `make new-service`, then the human-owned registration (A15) |
| `new-use-case` | A new business operation: `make new-use-case`, rules first, a RED test per rule (T1, T2) |
| `external-io` | A reference catalog (AP-1…AP-11), cited by the reviewers |

**Order for a branch:** `spec` → `tdd` (commit and push freely, as often as you like) → when
ready for `main`: `make check` → `tighten` → `harvest` (when `.work/` has working docs) →
`code-review` → mark the PR ready, or merge/push to `main`. `tighten` runs after the code works so
the reviewer sees the final version.

`new-service` and `new-use-case` drive the Copier templates in `tools/templates/`; the four
platform-library skills add each seam to a generated service.

**Agents** (all read-only):
- `code-reviewer` (opus), the gate.
- `architecture-reviewer` and `test-quality-reviewer` (sonnet).
- `security-reviewer` (opus).
- `explorer` (haiku), the cheap "where is X" finder that keeps the main context clean.

**Commands:** `/review [focus]`, `/security-review`, `/spec <description>`.

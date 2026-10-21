# Architecture conventions (A-rules)

The single source for architecture rules. Skills, rules files, reviewers and `AGENTS.md` cite
these IDs; `sb-agentkit lint` fails if a cited ID is not defined here. Each rule says how it is
enforced. "Review" means the code-review gate (`.claude/skills/code-review`) checks it.

## Layer model

```
interface/       FastAPI routers, SQLAdmin views/calculators, Kafka consumers, Temporal workflows+activities
infrastructure/  SQLAlchemy models+repositories, outbox publisher, external clients, settings
application/     ports.py (Protocols), dto.py, policies/ (pure calculators), use_cases/ (one per file)
domain/          entities, value objects, domain events, errors — invariants only
bootstrap.py     composition root: the only place adapters are constructed and wired
```
Dependencies point **down** only: interface → infrastructure → application → domain.

### A1 — Dependency rule
Imports point inward only: `interface` → `infrastructure` → `application` → `domain`. `bootstrap`
and the entrypoints (`main`, `worker`, `consumer`) sit above everything.
*Enforced:* import-linter `layers` contract per service in `.importlinter`.

### A2 — Pure inner layers
`domain/` and `application/` import only the standard library, `pydantic`, `sb_kernel`, and
their own inner layers. Never `sqlalchemy`, `fastapi`, `starlette`, `sqladmin`, `temporalio`,
`confluent_kafka`, `httpx`, `pydantic_settings`, `structlog`, or another `sb_*` library.
*Enforced:* import-linter `forbidden` contract per service.

### A3 — Business logic has exactly two homes
Business decisions live in `application/use_cases/` (the process: load, decide, persist,
emit) and `application/policies/` (pure calculations). `domain/` holds entities, value objects
and their invariants. `interface/` and `infrastructure/` make **no** business decisions: no
`if` on business state, no arithmetic on money, no rule lookups.
*Enforced:* review; `use-case-rules` check.
*Why:* a reviewer of an AI-written change reads two directories and knows they have seen
every rule.

### A4 — Use case shape
One use case per file: `use_cases/<verb>_<noun>.py`, class `<Verb><Noun>`. Ports are injected in
`__init__`, and it has one `async def __call__(self, command: <Command>) -> <Result>`. The module
docstring lists every business rule as `R1: …`, `R2: …`. Each rule has a unit test
`test_R<n>_<behaviour>` in `tests/unit/use_cases/test_<verb>_<noun>.py`.
*Enforced:* `use-case-rules` check (rule ↔ test binding); review (shape).

### A5 — Policies are pure
`policies/*.py` functions take and return values (pydantic models or domain value objects). They do
no I/O, don't read a clock or a random source, and give the same output for the same input.
They are the units that SQLAdmin acceptors expose for human verification.
*Enforced:* A2 contracts; `no-naive-now`; review.

### A6 — Ports and adapters
Ports are `typing.Protocol`s in `application/ports.py`. Adapters in `infrastructure/`
implement them. ORM models, SDK objects and HTTP responses never cross into `application/`:
repositories map to and from domain objects.
*Enforced:* A1/A2 contracts; review.

### A7 — Composition root
Only `bootstrap.py` constructs adapters and use cases. There are no module-level singletons, no
service locators, and no provider selection by string in the inner layers. FastAPI `Depends` appears
only in `interface/http`.
*Enforced:* review.

### A8 — Thin interface
A router, consumer, activity or admin view does three things: validate input, call a use case (or
a policy, for calculators), and map the result or error. It contains no queries and no rules.
*Enforced:* review.

### A9 — Services are islands
A service never imports another service. Services talk through events (`contracts/events`) or
HTTP APIs (`contracts/openapi`).
*Enforced:* import-linter `independence` contract across services; `sb-graph check`.

### A10 — Libraries never import services
`libs/py/*` never import from `services/*`. `sb_kernel` imports no other `sb_*` library.
*Enforced:* import-linter contracts.

### A11 — Events go through the outbox
State changes emit events only by writing to the transactional outbox in the same unit of work.
Consumers are idempotent through the inbox table. Nothing publishes to Kafka directly from a use
case.
*Enforced:* A2 (no `confluent_kafka` in inner layers); review.

### A12 — Deterministic workflows
Temporal workflow code does no I/O, doesn't read the clock or randomness, and doesn't use
non-deterministic iteration. Activities do the work, and each activity calls exactly one use case.
Workflow IDs are deterministic (`<name>-<tenant>-<business key>`). Activities retry, so every
activity (and the use case it calls) must be idempotent.
*Enforced:* replay tests; review.

### A13 — Tenancy is structural
Every tenant-scoped table has `tenant_id` and a Postgres RLS policy. The tenant comes from the
authenticated `RequestContext`, never from a request body or query parameter. The runtime DB role
has no `BYPASSRLS`.
*Enforced:* RLS isolation integration test per service; review; security review.

### A14 — Every state change is audited
Every use case that changes state writes an `audit_event` through the unit of work, in the same
transaction.
*Enforced:* review; use case rule tests.

### A15 — Deviations are recorded, never implied
Breaking a rule requires an ADR or a `tools/checks/allowlist.toml` entry with a reason. Existing
violations are debt, not precedent. Agents never loosen a guardrail to make a check pass: they
fix the code or stop and propose the change.
*Enforced:* guardrail files are human-owned (pre-edit hook + CODEOWNERS).

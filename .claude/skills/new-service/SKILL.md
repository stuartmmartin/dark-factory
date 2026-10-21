---
name: new-service
description: Create a new service (a new bounded context with its own data) from the Copier template with make new-service, then register it (tach.toml and .importlinter are human-owned), fill its CONTEXT.md and add its seams (events, workflows, acceptors, tables). Use before creating anything under services/.
---
# New service
Reference: [add a service](../../../docs/guides/add-a-service.md). Rules: A1, A2, A9 (layers and
boundaries), A13 (tenancy), A15 (guardrails are human-owned), T1 (test first).

**When.** A new service is a new bounded context that owns its own data: its own words
(`CONTEXT.md`), its own database and its own contracts. A new feature of an existing context is
a use case in that service (the `new-use-case` skill), not a service. When unsure, ask.

**Generate.**
1. `make new-service NAME=<snake_case>` (at most 24 characters; not `infra`, `core`, `init`,
   `tools`, `tests`, a Python keyword or stdlib module, `sb_*`, or an existing member). It renders
   `tools/templates/service` into `services/<name>` (the reference service's layout: settings,
   domain, application, fakes, infrastructure, the platform-tables migration, HTTP, admin,
   bootstrap, main, migrate, Dockerfile) with one placeholder use case, `Ping`
   (`GET /v1/ping`). It picks the next free host port, prints `REGISTER.md`, runs
   `uv sync --all-packages` and `make graph`.
2. Never copy a service by hand, and never edit the generated layout into a different shape.

**Register.** `services/<name>/REGISTER.md` holds every snippet. Two kinds of file:
- `tach.toml` and `.importlinter` are human-owned guardrails (A15): the pre-edit hook blocks
  you. Hand those snippets to a human (the tach module and source root; the `<name>-layers` and
  `<name>-pure-core` contracts; `<name>` added to `root_packages`, `testing-only-in-tests` and
  `libs-never-import-services`; the A9 `services-independent` contract or its new module).
- `compose/services.yml`, `.env.example` and `docs/CONTEXT-MAP.md` are ordinary files you
  paste into yourself. OpenAPI service discovery is automatic through the workspace graph.
Until the boundary snippets are in, `make check` fails; that is expected. `sb-graph check`
checks root registration plus the complete canonical layer/pure-core, library/service,
service-independence and test-only contracts. Partial contracts and import exemptions fail;
import-linter separately checks actual dependencies. Include all current non-kernel libraries
in pure-core restrictions. Then: `make openapi`, `make graph`, `make check`, delete `REGISTER.md`.

**Describe the context.** Fill `services/<name>/CONTEXT.md` (one entry per term: definition,
words to avoid, invariant) before the first use case, and add a row to
[the context map](../../../docs/CONTEXT-MAP.md) saying what the context publishes and consumes.

**First use case.** `make new-use-case SVC=<name> NAME=<verb_noun>` (the `new-use-case`
skill). Delete `Ping`, its route, its schema and its test once a real use case exists, and
re-run `make openapi`.

**Add each seam with its skill**, copying the reference service's file named here:
- a table: `alembic-migration` (a new revision with `enable_rls_sql` and the grants; see
  `services/ledger/migrations/versions/0001_initial.py`), plus a repository port, its SQL
  implementation, its fake and a contract suite (`services/ledger/tests/contract/`);
- an event published or consumed: `kafka-event` (`services/ledger/src/ledger/domain/events.py`,
  `interface/consumers/account_opened.py`, `consumer.py`, `contracts/events/*.json`);
- a scheduled or long-running job: `temporal-workflow`
  (`services/ledger/src/ledger/interface/workflows/`, `worker.py`);
- business math a human should check: `admin-acceptor`
  (`services/ledger/src/ledger/application/policies/allocation.py`,
  `interface/admin/acceptors.py`).
A worker or consumer process also needs its compose service (same shape as the reference
service's in `compose/services.yml`) and its layer is already in
the `<name>-layers` contract (`(worker) | (consumer) | (seed)`).

**Deploy.** Before the first deploy add `deploy/k8s/<kebab>/` in the reference service's shape
(`deploy/k8s/ledger/`). One convention: the Python package, `services/<name>/`, the compose names
and the `<NAME>_` env prefix keep `_`; the k8s directory, every Kubernetes resource name, the
`app.kubernetes.io/name` label and the image (`dark-factory-<kebab>`) use the hyphenated form
(`demo_svc` → `demo-svc`), because Kubernetes names are DNS labels. `images.yml` and `deploy.yml`
derive both spellings from the member, so never rename the service directory to match.

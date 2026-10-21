# Add a service

A service is a bounded context that owns its data: its own glossary, database, API and event
contracts. Every service is generated from one template, so they all share the reference
service's layout (`services/ledger`); nobody copies one by hand. Agents follow the
[`new-service` skill](../../.claude/skills/new-service/SKILL.md); this is the human version.

## Is it a service?

Create one when the work has its own words and its own data that another context should only
see through an API or an event. A new operation on data an existing service owns is a use case
in that service ([add a use case](add-a-use-case.md)).

## 1. Generate it

```sh
make new-service NAME=payments
```

The name is snake_case, at most 24 characters. It may not be `infra`, a compose profile (`core`,
`init`, `tools`), `tests`, a Python keyword, a standard-library module, an `sb_*` name or an
existing member or service. The target renders `tools/templates/service` into `services/payments`, picks the next
free API port on 127.0.0.1, prints `services/payments/REGISTER.md`, then runs
`uv sync --all-packages` and `make graph`.

What you get (the layout of the reference service, without its domain):

| Path | What |
|---|---|
| `src/payments/infrastructure/settings.py` | `PAYMENTS_*` settings; `environment` and `auth_mode` are required, dev auth and the admin only outside prod |
| `src/payments/application/` | ports (the unit of work Protocol), DTOs, `policies/`, and one placeholder use case, `Ping` |
| `src/payments/infrastructure/` | the ORM metadata with the platform tables, the SQL unit of work, a repositories module to fill |
| `src/payments/interface/` | `GET /v1/ping` (operationId `ping`), an admin with no views or acceptors yet |
| `src/payments/{bootstrap,main,migrate}.py` | composition root, `python -m payments.main` (uvicorn, redacted logs), `python -m payments.migrate` |
| `migrations/versions/0001_initial.py` | the platform tables (outbox, inbox, audit, idempotency) with their RLS and grants |
| `tests/` | the fakes (`tests/payments_fakes.py`), unit tests, the migration round-trip and HTTP tests |
| `Dockerfile`, `CLAUDE.md`, `CONTEXT.md` | dev/prod image, agent notes, the glossary to fill |

## 2. Register it (a human pastes this)

`REGISTER.md` holds the exact snippets. The boundary files, `tach.toml` and `.importlinter`, are
human-owned guardrails (A15): the agent hooks block edits to them, so you paste those:

- `tach.toml`: the source root and the `[[modules]]` entry;
- `.importlinter`: the service in `root_packages`, `testing-only-in-tests` and
  `libs-never-import-services`; two contracts (CLEAN layers, pure core); and the A9
  `services-independent` contract, rendered from the services that already exist (created with
  the second service, extended after that).

The rest an agent may paste itself: `compose/services.yml` (the migrate job and the API, on the
printed port), `.env.example` and `docs/CONTEXT-MAP.md` are ordinary files.
`make openapi` discovers service import names from the workspace graph; no manual list is needed.

pyright's strict globs and pytest's `testpaths` already cover every service. Until the snippets
are in, `make check` fails. `sb-graph check` verifies tach `source_roots`, import-linter
`root_packages`, pyright `include`, pytest `testpaths` and complete canonical service contracts:
CLEAN layer order, pure-core restrictions, library/service direction, test-only imports and
service independence. Missing members, partial contracts and import exemptions fail the check;
import-linter separately checks the actual dependency edges. Then run `make openapi`,
`make graph` and `make check`, commit `docs/generated/`, `uv.lock` and
`contracts/openapi/<name>.json` with the service, and delete `REGISTER.md`.

## 3. Describe the context

Fill `CONTEXT.md` (term, definition, words to avoid, invariant) before the first use case, and
add the context to [the context map](../CONTEXT-MAP.md).

## 4. Build it

- Use cases: `make new-use-case SVC=payments NAME=<verb_noun>` ([add a use case](add-a-use-case.md)).
  Delete `Ping` and its route and test once a real one exists.
- Tables: the `alembic-migration` skill (a new revision with RLS and grants).
- Events: the `kafka-event` skill. Workflows: the `temporal-workflow` skill. Acceptors for
  business math: the `admin-acceptor` skill. Each points at the reference service's files.
- Kubernetes manifests before the first deploy, in the reference service's shape. One naming
  convention everywhere: Kubernetes names cannot contain `_`, so the k8s directory, every
  resource name and the image use the hyphenated form (`payment_links` →
  `deploy/k8s/payment-links/`, `payment-links-api`, `ghcr.io/<owner>/dark-factory-payment-links`);
  the Python package, the service directory (`services/payment_links/`), the compose names and
  the env prefix keep the underscores. `images.yml` builds each member from its real directory
  with its package as `SERVICE`; `deploy.yml` accepts either spelling of the service and deploys
  the hyphenated directory.

The generator is tested: `tools/checks/tests/test_templates.py` renders two services into a
temporary directory and runs their unit tests (in one pytest session), ruff, pyright, the
import contracts from their own `REGISTER.md` and `sb-checks`.

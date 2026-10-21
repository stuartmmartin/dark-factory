# Environment setup

This is the one how-to for a working local environment. CI runs it: every command in a fenced
block tagged `sh env-setup` is extracted and executed, in order, on a clean runner
(`uv run sb-checks doc-commands docs/environment_setup.md --run`). If this page stops working,
CI fails. Blocks tagged plain `sh` are informational and are never run.

At the end you have Postgres, Kafka and Temporal running in Docker, the `ledger` service
(API, worker and consumer) running against them with hot reload, a seeded demo account, and a
green unit-test run.

## 1. Prerequisites

You need macOS or Linux, git, Docker with at least 6 GB of RAM for the VM (Docker Desktop,
OrbStack or colima), `make`, `uv` and `mise`. `mise` installs the other pinned tools (Python,
`uv`, `gitleaks`, `kustomize`, `kubeconform`; see `mise.toml`). These commands are not run by CI:

```sh
brew install --cask docker    # or: brew install orbstack
brew install git mise uv
```

On Apple Silicon, the Temporal time-skipping test server that the workflow tests use is
downloaded on first use as an x86_64 binary and needs Rosetta:
`softwareupdate --install-rosetta --agree-to-license`.

The repository targets GNU make 3.81 (the macOS default), so no newer make is needed.

## 2. Clone and bootstrap

```sh
git clone <repo-url> dark_factory && cd dark_factory
```

Then, from the repository root:

```sh env-setup
make bootstrap
```

`make bootstrap` runs `mise install` (pinned tools), `uv sync --all-packages` (one `.venv` for the
whole workspace), installs `pyright` as a tool (the Claude LSP plugin needs
`pyright-langserver` on `PATH`), and installs the pre-commit hooks. Run it again in every new
worktree: the Claude hooks only work when the worktree has a `.venv`.

## 3. Configure

```sh env-setup
cp -n .env.example .env || true
```

`.env` is gitignored and holds local overrides. Every value in `.env.example` is a dev-only
default, so leaving all of them alone is fine on a normal machine. Never commit `.env`, and never
put real secrets in it.

| Variable | Purpose | Safe at the default? |
|---|---|---|
| `SB_PG_PORT` | Host port for Postgres (default 5432) | Yes, unless something else uses 5432 |
| `SB_KAFKA_PORT` | Host port for Kafka (9092). It is also the port advertised to host clients | Yes, unless 9092 is taken |
| `SB_TEMPORAL_PORT` | Host port for the Temporal gRPC API (7233) | Yes, unless 7233 is taken |
| `SB_TEMPORAL_UI_PORT` | Host port for the Temporal UI (8233) | Yes, unless 8233 is taken |
| `SB_KAFKA_UI_PORT` | Host port for Kafka UI (8080), started by `make up-tools` | Yes, unless 8080 is taken |
| `SB_LEDGER_API_PORT` | Host port for the ledger API and admin (8001) | Yes, unless 8001 is taken |
| `SB_PG_ADMIN_PASSWORD` | Password of the Postgres `sb_admin` superuser (used to create databases) | Yes, dev only |
| `SB_MIGRATOR_PASSWORD` | Password of `sb_migrator`, the role that owns the schema and runs migrations | Yes, dev only |
| `SB_APP_PASSWORD` | Password of `sb_app`, the role the services connect as (row-level security applies) | Yes, dev only |
| `SB_READONLY_PASSWORD` | Password of `sb_readonly` | Yes, dev only |
| `SB_AUTH_MODE` | Service auth mode. `dev` trusts `X-Tenant-Id` and `X-Actor` headers | Yes. Never use `dev` outside local development; services refuse it in a prod environment |
| `SB_ADMIN_USERNAME` | SQLAdmin login | Yes, dev only |
| `SB_ADMIN_PASSWORD` | SQLAdmin password | Yes, dev only |
| `SB_ADMIN_SECRET_KEY` | Signs the admin session cookie. Must be at least 32 characters | Yes for dev. Do not shorten it: the admin refuses a shorter key |

The compose files require `SB_AUTH_MODE`, every `SB_*_PASSWORD`, `SB_ADMIN_USERNAME` and
`SB_ADMIN_SECRET_KEY` (`${VAR:?}`); only the API containers receive the `SB_ADMIN_*` values. If your `.env` predates one of them, `make up`, `make down`
and `make logs` all fail at once with a message naming the missing variable. Copy the new key from
`.env.example` into `.env`. `cp -n` never overwrites an existing `.env`, so it does not do this
for you.

Verify the machine:

```sh env-setup
make doctor
```

`make doctor` checks, in order: that `uv` and `docker` are on `PATH` and that the Docker daemon
and Compose v2 respond (each a failure if not); that `mise`, `gitleaks` and
`pyright-langserver` are on `PATH` and that the agent hooks are installed
(`.venv/bin/sb-agentkit`, from `make bootstrap`) (warnings); that the four appliance ports
(`SB_PG_PORT`, `SB_KAFKA_PORT`, `SB_TEMPORAL_PORT`, `SB_TEMPORAL_UI_PORT`) are free or already
used by this stack (a warning otherwise); and that `SB_ADMIN_SECRET_KEY` is at least 32
characters (a warning). It does not check `SB_LEDGER_API_PORT` or the Kafka UI port. It exits
non-zero only on a failure; a warning is advice.

## 4. Start the appliances

```sh env-setup
make up infra
```

This starts Postgres, Kafka and Temporal (compose profile `core`) and waits until they are
healthy. It then creates one Kafka topic per file in `contracts/events/` (auto-create is off in
compose, so a new event needs its contract file first). Data lives in named Docker volumes and
survives `make down`.

| Appliance | Where | Notes |
|---|---|---|
| Postgres 17 | `localhost:5432` | Roles `sb_admin`, `sb_migrator`, `sb_app`, `sb_readonly`; passwords in `.env` |
| Kafka 4.1 | `localhost:9092` | Single KRaft broker |
| Temporal | `localhost:7233` | `temporal server start-dev`, sqlite in a volume |
| Temporal UI | http://localhost:8233 | Namespace `default` |
| Kafka UI | http://localhost:8080 | Only after `make up-tools` |
| Ledger API docs | http://localhost:${SB_LEDGER_API_PORT:-8001}/docs | After `make up ledger` (section 5) |
| Ledger SQLAdmin | http://localhost:${SB_LEDGER_API_PORT:-8001}/admin | Login with `SB_ADMIN_USERNAME` / `SB_ADMIN_PASSWORD` from `.env` (dev defaults: `admin` / `admin_dev`) |

Every published port binds to `127.0.0.1` only. The ports above are the defaults; each moves with
its `SB_*_PORT` variable.

Start the optional tools (Kafka UI) with `make up-tools`, and look at the containers with
`make ps`.

## 5. Start the ledger service

```sh env-setup
make up ledger
```

`make up ledger` makes sure the appliances are up, runs the `ledger-migrate` job (it creates the
`ledger` database if needed and upgrades it to head), then starts `ledger-api`, `ledger-worker`
and `ledger-consumer` and waits for the API health check. To run a migration by hand use
`make db-migrate SVC=ledger`.

Verify it is healthy. The retry flags cover the last seconds of startup. If you moved the API
port with `SB_LEDGER_API_PORT`, export that variable in your shell (`export SB_LEDGER_API_PORT=8002`)
for this command: bash does not read `.env`, so without the export it falls back to 8001.

```sh env-setup
curl -fsS --retry 10 --retry-delay 3 --retry-all-errors http://localhost:${SB_LEDGER_API_PORT:-8001}/health/ready
```

Then open http://localhost:${SB_LEDGER_API_PORT:-8001}/docs (the OpenAPI UI) and
http://localhost:${SB_LEDGER_API_PORT:-8001}/admin
(SQLAdmin, `admin` / `admin_dev` unless you changed them).

## 6. Seed and try it

```sh env-setup
make seed SVC=ledger
```

This opens the account "Operating cash" (USD) for the demo tenant
`00000000-0000-0000-0000-0000000000d3`, by calling the `OpenAccount` use case (so it writes the
audit event and the outbox row too). It prints `tenant_id=` and `account_id=`. Re-running it
replays the first result (`(replayed)`), because it uses a fixed idempotency key.

Post a balanced entry with `ledger-cli`, the demo client (`services/ledger/src/ledger/client`).
It defaults to this API and the demo tenant. The idempotency keys make re-running these
commands replay the first result instead of opening a second "Owner equity":

```sh env-setup
uv run ledger-cli open "Owner equity" --idempotency-key setup-owner-equity
uv run ledger-cli transfer 1000.00 --from "Owner equity" --to "Operating cash" --description "Initial funding" --idempotency-key setup-funding
uv run ledger-cli accounts
uv run ledger-cli balance "Operating cash"
```

`accounts` lists "Operating cash" at 1000.00 and "Owner equity" at -1000.00: a balance is debits
minus credits. The README's "Getting started" walks through more.

Things to try. The dev auth mode needs the `X-Tenant-Id` header on every call:

```sh
TENANT=00000000-0000-0000-0000-0000000000d3
curl -sS -X POST http://localhost:${SB_LEDGER_API_PORT:-8001}/v1/accounts \
  -H "X-Tenant-Id: $TENANT" -H "Idempotency-Key: my-first-account" \
  -H 'Content-Type: application/json' -d '{"name": "Petty cash", "currency": "USD"}'
# repeat the same command: 200 (not 201) with the same account id, and no second account
# GET /v1/accounts/<id> with the same tenant: the account
# GET /v1/accounts/<id> with another tenant id: 404 (never "forbidden")
```

- **The event flow.** Run `make up-tools`, open http://localhost:8080, and look at topic
  `ledger.account.opened.v1`: each opened account is an event there, published by the outbox relay
  in `ledger-consumer`. The same process consumes it and updates the tenant's account count
  (`RecordAccountOpened`). `make logs ledger` shows both sides.
- **The acceptor.** In SQLAdmin, open the "Allocation" acceptor from the menu, enter a total
  and weights, and compare the parts with your own arithmetic. It runs the same pure
  policy (`allocate`) as the code. The account list view shows no rows: it runs as `sb_app` with
  no tenant set, so row-level security hides everything. That is expected
  (see [`architecture/admin.md`](architecture/admin.md)).
- **The workflow.** The worker serves task queue `ledger` in Temporal namespace `default`. The
  thin slice has no schedule, so the `AccountCountSnapshot` workflow only runs when a test (or you)
  starts it. See [`architecture/workflows.md`](architecture/workflows.md).

## 7. Hot reload

`make up ledger` builds an image that holds only third-party dependencies. The service source
(`services/ledger/src`, `services/ledger/migrations`) and the platform libraries (`libs/py`) are
bind-mounted and installed editable when the container starts, so almost no edit needs a rebuild.

- **API:** reloads by itself when you save a file under `services/ledger/src` or `libs/py`. Watch
  it with `make logs ledger`.
- **Worker and consumer:** run exactly as in production, with no reloader. After editing their
  code (or anything they import), run `make restart ledger`. `make up ledger` does not recreate
  a container whose image and configuration are unchanged, so it does not pick up the edit.
- **Rebuild** with `make build ledger` only after `uv.lock` or a `pyproject.toml` dependency
  changed (`make up ledger` rebuilds as needed, but `make build` is the explicit way).
- **Migrations:** after adding a revision, run `make db-migrate SVC=ledger`.

## 8. Run the tests

```sh env-setup
make test-unit
```

- `make test-unit` runs everything not marked `integration`. It needs no Docker.
- `make test` runs everything, including integration tests. They start their own Postgres and
  Kafka containers through testcontainers, so they need Docker running but do **not** need
  `make up infra`. The workflow tests do not use a container: they run Temporal's
  time-skipping test server, which the `temporalio` SDK downloads and starts itself.
- Narrow the run with `make test PKG=services/ledger ARGS='-k name'`; `make test-integration` runs
  only the integration tests.
- `make check` runs lint, types, contracts, graph/OpenAPI checks, all tests and logic coverage;
  `make check-fast` is the quick gate that Claude's Stop hook runs. CI also has infrastructure,
  scanner and setup gates: see the [verification matrix](verification.md).

## 9. Claude Code setup

The committed `.claude/settings.json` already enables the `pyright-lsp` plugin. Claude Code
installs it the first time it prompts you, and `make bootstrap` puts `pyright-langserver` on
`PATH` for it. The same file wires the hooks (`sb-agentkit hook ...`), which:

- block edits to secrets (`.env*` except `.env.example`), guardrail files and merged migrations;
- redirect raw `pytest`, `alembic` and `docker compose` to their `make` targets;
- run `ruff` and `pyright` on every Python file Claude edits;
- when Claude stops, re-check the guardrails and run `make check-fast`.

Run `/review` (or `make review`) before you claim work is done: it runs the code-review gate on
your branch and returns a verdict. Details are in [`agents/hooks.md`](agents/hooks.md) and
[`agents/review-gates.md`](agents/review-gates.md).

Guardrail files (`tach.toml`, `.importlinter`, `ruff.toml`, `.github/`, `Makefile` and so on) can
only be edited by a human who launches Claude with `SB_ALLOW_GUARDRAIL_EDITS=1` (or a
comma-separated list of the paths to allow). Agents never set it. If the hooks seem inactive, the
session-start message says so: run `make bootstrap` in that worktree.

## 10. Worktrees and parallel stacks

Compose derives its project name from the directory name (`sb-<directory>`), so each git
worktree gets its own containers and volumes and does not disturb another checkout. Only the host
ports can collide. Override them in that worktree's `.env` (or in the environment) before
`make up`:

```sh
git worktree add ../dark_factory-feature -b feature/x
cd ../dark_factory-feature && make bootstrap && cp -n .env.example .env
# edit .env: SB_PG_PORT=5433 SB_KAFKA_PORT=9093 SB_TEMPORAL_PORT=7234 SB_TEMPORAL_UI_PORT=8234 \
#            SB_KAFKA_UI_PORT=8081 SB_LEDGER_API_PORT=8002
```

You can also set `COMPOSE_PROJECT_NAME` yourself (`make up infra COMPOSE_PROJECT_NAME=sb-x`).
Inside the containers the services always talk to each other on the internal ports, so only the
host-facing ports need to differ. `make doctor` tells you which appliance ports are taken (it
does not check `SB_LEDGER_API_PORT`).

## 11. Teardown and reset

```sh env-setup
make down
```

`make down` stops and removes the containers and keeps the volumes (your data). If a step above
fails half way, run `make down` yourself; CI does not need it. `make reset` also deletes the
volumes (Postgres and Temporal data) after a confirmation prompt; `make reset CONFIRM=1` skips the
prompt and is required when there is no terminal.

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `port is already allocated`, or `make doctor` warns a port is used | Another process holds it. Set the matching `SB_*_PORT` in `.env` (section 3), then `make up` again. |
| Containers exit or the machine crawls | Docker has too little memory. Give the Docker VM at least 6 GB. `make ps` shows which containers are down. |
| `make up ledger` waits, then fails on Kafka or the API | Kafka was not ready yet. Wait a moment and re-run `make up ledger`; `make logs ledger` shows the error. `make ps` shows whether `kafka` is healthy. |
| `required variable SB_... is missing` | Your `.env` predates that key. Copy it from `.env.example` (section 3). |
| A migration fails, or the schema does not match the code after you changed a migration | The volume still holds the old schema. Fix the migration with a new revision when it has been merged; for a local-only change run `make reset`, then `make up ledger`. Never edit a merged migration. |
| Workflow tests fail to start the Temporal test server on Apple Silicon | Install Rosetta (section 1). |
| `uv` resolves or downloads slowly, or fails on a corrupt cache | `uv cache clean`, then `make sync`. |
| The worker or consumer ignores your edit | They have no reloader: `make restart ledger` (section 7). |
| Claude hooks do nothing | No `.venv` in this worktree: `make bootstrap`. |

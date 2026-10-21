# dark_factory

An example monorepo set up to run as a **dark factory**: AI agents write most of the code,
machines check every change, and humans set the business rules and approve the merge.

It is a working Python 3.13 / FastAPI codebase on Postgres, Kafka and Temporal. What it shows is
the scaffolding around the code:

- **Business logic has two homes.** Use cases and pure policies only. Each use case lists its
  rules (`R1`, `R2`…), and each rule has a test named after it.
- **Test-driven, with evidence.** Agents paste the failing test run before the passing one. Unit
  tests use fakes, not mocks. Integration tests run against real infrastructure.
- **Guardrails agents can't edit.** Lint, type, boundary, hook and CI config are human-owned.
  Claude Code hooks block edits to them, and a check at the end of every session catches
  anything that slipped through.
- **Conventions are build failures.** AST checks reject floats for money, direct clock calls,
  env reads outside settings, and mocks in unit tests.
- **AI review in CI.** Security, architecture and engineering reviewers gate every PR. A finding
  that doesn't quote the diff line it's about is dropped.
- **Knowledge compounds.** Working docs stay out of git. A `harvest` step moves what lasts into
  tests, `CLAUDE.md`, `CONTEXT.md` and ADRs.

The demo is `ledger`, a small multi-tenant double-entry bookkeeping service, plus `ledger-cli`, a
command-line client for it.

## Setup

You need macOS or Linux, git, `make`, Docker with at least 6 GB of RAM (Docker Desktop, OrbStack
or colima), [`uv`](https://docs.astral.sh/uv/) and [`mise`](https://mise.jdx.dev/). On macOS:

```sh
brew install --cask docker    # or: brew install orbstack
brew install git mise uv
```

Clone the repo and bootstrap it. This installs the pinned tools, the Python workspace and the git
hooks:

```sh
git clone https://github.com/stuartmmartin/dark-factory.git && cd dark-factory
make bootstrap
cp -n .env.example .env       # local, dev-only defaults; never commit .env
make doctor                   # checks tools, Docker and ports
```

Start Postgres, Kafka and Temporal, then the ledger service. The second command runs the database
migrations and waits until the API is healthy:

```sh
make up infra
make up ledger
```

The API docs are at http://localhost:8001/docs. The admin is at http://localhost:8001/admin
(`admin` / `admin_dev`). `make help` lists every command. Full details and troubleshooting are in
[docs/environment_setup.md](docs/environment_setup.md), which CI runs on a clean machine.

## Getting started

This walks through a small set of books end to end with `ledger-cli`. Each account is a ledger.
Every journal entry must balance: total debits equal total credits.

By default the client talks to `http://localhost:8001` as the demo tenant. Set `LEDGER_CLI_URL`
or `LEDGER_CLI_TENANT`, or pass `--url` or `--tenant`, to change that. The client finds accounts
by exact name, so names need to be unique. If you have already run `make seed` or the setup
guide's example, start from a fresh tenant: `export LEDGER_CLI_TENANT=$(uuidgen)`.

**1. Open some ledgers.**

```sh
uv run ledger-cli open "Owner equity"
uv run ledger-cli open "Operating cash"
uv run ledger-cli open "Savings"
uv run ledger-cli open "Rent"
```

```text
opened Owner equity (USD) 60666b5b-4da3-4ce3-9a9b-9ffa10bf4657
...
```

**2. Record transactions.** `transfer` posts a two-line entry. It debits the `--to` account and
credits the `--from` account:

```sh
uv run ledger-cli transfer 5000.00 --from "Owner equity" --to "Operating cash" --description "Initial funding"
uv run ledger-cli transfer 1500 --from "Operating cash" --to "Savings"
```

`post` takes any number of `side:account:amount` lines, as long as they balance:

```sh
uv run ledger-cli post "October rent" "debit:Rent:1200.00" "credit:Operating cash:1200.00"
```

```text
posted a69954ae-69cb-43a5-867b-6a78a2542e7f: October rent (USD)
  debit         1200.00  Rent
  credit        1200.00  Operating cash
```

**3. Read the books.** A balance is debits minus credits, so the equity account reads negative and
all the balances sum to zero:

```sh
uv run ledger-cli accounts
uv run ledger-cli balance "Operating cash"
```

```text
NAME                     CURRENCY        BALANCE  ID
Owner equity             USD            -5000.00  60666b5b-…
Operating cash           USD             2300.00  c9fa8b0a-…
Savings                  USD             1500.00  5986502b-…
Rent                     USD             1200.00  88779bd4-…

debits          5000.00 USD
credits         2700.00 USD
balance         2300.00 USD
```

**4. See the rules hold.** The service rejects entries that don't balance. It also rejects amounts
with more precision than the currency allows: it never rounds. Each refusal exits non-zero and
changes nothing:

```sh
uv run ledger-cli post "Oops" "debit:Rent:100.00" "credit:Operating cash:99.00"
# error: validation_failed: entry does not balance: debits USD 100.00, credits USD 99.00
uv run ledger-cli transfer 10.005 --from Savings --to Rent
# error: validation_failed: USD 10.005 has more precision than USD allows
```

Tenants are isolated by Postgres row-level security. Run `uv run ledger-cli --tenant
$(uuidgen) accounts` and the list is empty.

**5. Check the arithmetic in the admin.** The admin's acceptors run the same policy the API
uses, so a reviewer can check every `ledger-cli` entry by hand. They never read or write the
books: account names are just labels.

1. Open http://localhost:8001/admin. Enter username `admin` and password `admin_dev`, then click
   **Login**.
2. In the top menu, click **Acceptors**, then **Transfer**. This is `ledger-cli transfer`.
3. Fill in the form and click **Run**:
   - **Amount**: `5000.00`
   - **Currency**: leave blank (it defaults to `USD`)
   - **From account**: `Owner equity`
   - **To account**: `Operating cash`

   The **Result** table shows the two lines from step 2: `debit 5000.00 Operating cash` and
   `credit 5000.00 Owner equity`. Both totals are `5000.00`, and `version` is the policy version.
4. Change **Amount** to `10.005` and click **Run** again. A red box shows `USD 10.005 has
   more precision than USD allows`, the same refusal the CLI printed in step 4.
5. Click **Acceptors**, then **Journal entry**. This is `ledger-cli post`. Under **lines**, enter
   `debit 1200.00, credit 1200.00` and click **Run**. Both totals read `1200.00`. Change it
   to `debit 100.00, credit 99.00` and click **Run**. The red box reads `entry does not
   balance: debits USD 100.00, credits USD 99.00`.
6. Click **Accounts**. The list says `Showing 1 to 0 of 0 items`, even though you opened four
   accounts. The admin has no tenant, so row-level security hides every tenant's rows (ruling D9
   in [docs/architecture/admin.md](docs/architecture/admin.md)). Use `ledger-cli accounts` to read
   real balances.
7. Click **Logout** when you're done.

When you're done, run `make down` (your data stays in Docker volumes). Run `make reset` to delete
it too.

## Working in the repo

- `make test-unit` runs the fast tests. `make check` is the full local gate: lint, types,
  architecture contracts, OpenAPI drift, tests and 100% coverage of the logic layers.
- Agents start at [AGENTS.md](AGENTS.md). Humans start at [docs/README.md](docs/README.md).
- [docs/agents/](docs/agents/README.md) explains the hooks, skills, review gates and the
  [dark-factory runbook](docs/agents/dark-factory-runbook.md) for long autonomous runs.
- [services/ledger/](services/ledger) is the reference service. Its `CONTEXT.md` is the domain
  glossary, and its use cases list their business rules.

## License

[MIT](LICENSE)

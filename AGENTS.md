# dark_factory — agent instructions

Family-office monorepo: Python 3.13 / FastAPI services on Postgres, Kafka and Temporal.
Most code is written by agents; humans verify business logic. Optimise for **reviewable
business logic** and **passing the machines on the first try**.

## Make is the shortcut, not a fence
`make help` lists the targets. Raw `pytest`, `alembic`, `docker compose` and `psql` are fine too,
and you may add or change make targets. The ones you need most:
- `make test PKG=<dir-or-file> ARGS='-k name'`, `make test-unit`, `make test-affected` (T11)
- `make fmt`, `make lint`, `make typecheck`, `make contracts`
- `make check-fast` (lint + affected unit tests) runs when you stop; `make check` is the full gate
  before merging to main ([matrix](docs/verification.md))
- `make graph` after changing members or public APIs (commit `docs/generated/`)
- `make affected`, `make blast-radius T=<member>`, `make deps T=<member>` show a change's reach
- Local stack: `make up infra|<svc>`, `make db-migrate|db-shell SVC=<svc>`, `make ports`

## Worktrees and parallel work
- One worktree per piece of work (`EnterWorktree`, or `git worktree add .claude/worktrees/<slug>
  -b <type>/<slug> main`). Hooks use the main checkout's `.venv` until the worktree has its own;
  `uv run` syncs the worktree's own environment on first use.
- Every test run gets its own throwaway Postgres/Kafka (testcontainers), so worktrees never share
  a test database or wait for each other. Never point tests at the `make up` stack.
- Each worktree's `make up` stack has its own compose project and host ports (`make ports`).
- Commit and push your branch freely. Land on `main` once the branch is ready (see Definition of done).

## Find code without reading everything
1. `docs/generated/module-index.md` lists every module's purpose and public API. Read it before opening files.
2. `make blast-radius T=<member>` shows who depends on what you are changing.
3. Use the LSP (go-to-definition, references) before grep. Use grep before reading whole files.
4. The service's `CLAUDE.md` holds its gotchas; its `CONTEXT.md` holds the domain glossary.

## Where code goes (CLEAN, enforced by import contracts)
- Business rules live ONLY in `application/use_cases/` and `application/policies/` (A3).
- A use case lives in one file, has one class and one `__call__`, and lists its rules as `R1:`,
  `R2:` in the docstring. Each rule has `test_R<n>_*` (A4, T2).
- Policies are pure functions: no I/O, no clock (A5). Humans verify them via SQLAdmin acceptors.
- Domain holds entities, value objects and invariants. Interface code stays thin (A8).
- Dependencies point inward (A1). The inner layers import no frameworks (A2).
- Services never import services (A9). Events go through the outbox (A11).

## Non-negotiables
- **TDD** (T1): write the failing test, show it fails for the right reason, then implement.
  Use the `tdd` skill.
- **Fakes, not mocks**, in unit tests (T3). Integration tests use real infra (T5).
- **Money is Decimal** via `sb_kernel.Money`, never float (C3). **Time via `Clock`** (C4).
- **Config only in `settings.py`** (C5). **Timeouts on all I/O** (C6).
- **Tenancy** comes from the request context and is enforced by RLS (A13). **Audit every state
  change** (A14).
- **Never edit guardrails** to pass a check: boundary, lint and type config (`tach.toml`,
  `.importlinter`, `ruff.toml`, `pyrightconfig.json`, `tools/checks/`), hooks and CI (`.claude/`
  settings and agents, `.github/`, `tools/agentkit/`), and `docs/conventions/`. The
  full list is the "Human-owned guardrails" section of `.github/CODEOWNERS`. Fix the code, or stop
  and propose the change (A15). Edits through tools are blocked, and any change (even via Bash)
  is re-checked when you stop. Only a human sets `SB_ALLOW_GUARDRAIL_EDITS`, when launching Claude.
- **Working docs are never committed.** Specs, plans, ledgers, investigations and notes go in
  gitignored `.work/<slug>/`, even when a skill or plugin names another path (such as
  `docs/superpowers/`). The `harvest` skill moves what lasts into code, tests, `CLAUDE.md`,
  `CONTEXT.md`, an ADR or a ticket.
- **Never read or edit `.env`** (C14). **Never edit a merged migration**. Create a new revision instead.

## Definition of done
While working: a failing test first, then green (evidence in your report); the tests of the
members you touched pass; commit in small steps. No per-commit review or full suite.

Before the branch goes into `main` (once per branch, not per commit or task):
1. `make check` passes, and `make graph` was re-run if members or public APIs changed.
2. `tighten`, then `harvest` if the branch had working docs (the PR lists `Knowledge harvested`).
3. The `code-review` skill returned **PASS** (use `/review`). No "PASS with warnings".
4. Land it: mark the PR ready (CI reviews non-draft PRs), or merge/push to `main` when the human
   asks for it. Never force-push.

## When to stop and ask
- Any change to an `R<n>` rule's meaning, money rounding, tenancy/RLS, auth, or audit behaviour.
- A destructive migration: drops, renames, or anything that isn't expand-then-contract.
- A guardrail that seems wrong, or a failure that you believe was already there before your change.

## More context (read only when relevant)
- Local setup, ports and troubleshooting (CI-run): [environment setup](docs/environment_setup.md)
- Conventions (rule IDs): [architecture](docs/conventions/architecture.md),
  [coding](docs/conventions/coding.md), [testing](docs/conventions/testing.md)
- How the AI scaffolding works: [docs/agents/README.md](docs/agents/README.md)
- Long autonomous runs: [docs/agents/dark-factory-runbook.md](docs/agents/dark-factory-runbook.md)
- Decisions: `docs/adr/`.

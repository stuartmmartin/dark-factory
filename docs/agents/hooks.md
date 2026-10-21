# Hooks

Configured in `.claude/settings.json` and implemented and tested in `tools/agentkit`
(`sb-agentkit hook <name>`). `tools/agentkit/hook.sh` launches them from this checkout's `.venv`,
else the main checkout's, so a fresh worktree is guarded without its own `make bootstrap`. Exit code 2 blocks the action (or, after an action, feeds the message
back) and sends the message to the agent. Every hook resolves the repo that owns its target (the
nearest directory with a `.git` marker), so a nested worktree such as `.claude/worktrees/w1` is
guarded as its own repo.

| Hook | When | What |
|---|---|---|
| session start | When a session starts | Warns if neither this checkout nor the main checkout has `.venv/bin/sb-agentkit`, because then every hook below is inactive. Never blocks. |
| `pre-read` | Before Read, Grep, Glob | Blocks `.env*` (except `.env.example`), with no override. Covers Grep's `path`/`glob` and Glob's `path`/`pattern`; Grep's content regex is not a path, so searching for the text `.env` is fine. |
| `pre-edit` | Before Edit/Write | Blocks `.env*` (except `.env.example`), with no override. Blocks human-owned guardrails and anything under `~/.claude/`. Blocks edits to migrations already on `origin/main`. |
| `pre-bash` | Before Bash | Blocks reading `.env`, force-push (`--force`, `-f`, `+ref`), `--no-verify`/`-n` and `core.hooksPath` overrides, also through wrappers such as `uv run`, `timeout`, `sudo`, `xargs` and `bash -c`. Raw `pytest`, `alembic`, `docker compose` and `psql` are allowed, as is pushing to `main`. Quoted `;`, `|`, `&&` are argument text; an unparseable command still gets a conservative scan for those high-risk patterns. |
| `post-edit` | After editing a `.py` file | `ruff check --fix` (never deleting unused imports or commented-out code, so test-first edits survive), `ruff format` and `pyright` on that file only. Leftover lint errors, and pyright errors in `src`, go back to the agent; pyright errors in `tests/` are passed back as information, not a block. |
| `stop` | When the agent tries to finish | 1. `guardrail-diff`: guardrail files changed since this session's baseline (else the merge-base with main), committed, uncommitted or untracked, and not covered by the override. 2. For any changed paths (including committed, staged, untracked and configuration changes), runs `make check-fast BASE=<comparison commit>` (lint + affected unit tests), unless the working state (HEAD plus a tree of every non-ignored file) equals the one the last passing run saw this session (`stop-passed-<session>` beside the session baseline). `SB_STOP_CHECK=0`, set by a human at launch, skips check-fast; the guardrail check still runs. Git inspection errors block completion; guardrail and check failures are combined. A repeated failed Stop emits a user-visible BLOCKED `systemMessage` and permits escalation instead of requesting another model turn; it is not a verification PASS. Subagents have no stop hook of their own: the parent's covers their changes. |

## Guardrails
The list lives in one place, `tools/agentkit/src/sb_agentkit/guardrails.py`, and is shared by
`pre-edit`, `guardrail-diff` (Stop) and CI triage. The "Human-owned guardrails" section of
`.github/CODEOWNERS` lists the same paths; a test fails if the two drift. They are the files that
could loosen a check: `tach.toml`, `.importlinter`, `tools/checks/allowlist.toml` and
`tools/checks/src/`, `ruff.toml`, `pyrightconfig.json`, `conftest.py`, `.pre-commit-config.yaml`,
`.coveragerc`, `.claude/settings.json` and `settings.local.json`,
`.claude/agents/`, `.claude/skills/code-review/`, `tools/agentkit/`, `.github/`, `.git/hooks/`
and `docs/conventions/`. Daily-work files such as `pyproject.toml`, the `Makefile` and `mk/*.mk`
stay editable (CODEOWNERS still reviews them; CI runs the gates).

`pre-edit` only sees the Edit/Write tools, so a guardrail changed through Bash (`sed -i`, `cp`)
is caught by the Stop hook instead. Run the same check yourself with
`uv run sb-agentkit guardrail-diff` (exit 1 lists the paths). It is deliberately not a
pre-commit hook: humans commit guardrail changes.

**Changing a guardrail deliberately:** a human sets `SB_ALLOW_GUARDRAIL_EDITS` when launching
Claude. `SB_ALLOW_GUARDRAIL_EDITS=1` allows every guardrail (and `~/.claude/`); a
comma-separated list of repo-relative paths or globs allows only those, e.g.
`SB_ALLOW_GUARDRAIL_EDITS='tach.toml,.github/workflows/**'`. Agents never set it. CODEOWNERS
still requires an owner's review of the PR.

If neither this checkout nor the main checkout has `.venv/bin/sb-agentkit`, the hooks fail as
non-blocking errors and the session-start warning says so. Run `make bootstrap` once in the main
checkout; a worktree needs its own only to run its own (edited) agentkit.

**Session baseline.** The first `pre-edit`, `pre-bash` or `pre-read` call of a session records
`git rev-parse HEAD` in `<git dir>/sb-agentkit/session-base-<session_id>` (the git dir of the
worktree that owns the session, so linked worktrees get their own). It is written once, never
overwritten, and never in the worktree. `stop` and `guardrail-diff` compare against the baseline
of the current session, so a guardrail change a human committed before the session is not
flagged, and fall back to the merge-base with main when there is no baseline (for example no
`session_id`). If neither baseline nor merge-base can be inspected, completion fails closed.
Uncommitted work present before the session is included: the hook does not attribute ownership
and must never advise reverting another person's changes. Nothing in `.claude/settings.json`
is needed for it.

Stop is local feedback, not proof that the full `make check` or review gate passed, and not an
atomic snapshot of a concurrently edited tree. CI and human review remain the merge gates.

The baseline lives in `.git/`, which Bash can write, so an agent could in principle rewrite it.
The merge-base with main stays as the backstop (CI and CODEOWNERS review still apply), and a
recorded commit that is unreachable or not a full hash is ignored in favour of the merge-base.

**Accepted exemption.** `pre-read` does not block a Grep/Glob whose last path component is a pure
wildcard (`*`, `**`, `*.*`, e.g. `Grep glob=*`, `**/*`, `src/**/*`): such a search lists or greps
files broadly and blocking it would break ordinary work. Globs that name a secret pattern
(`*.env`, `?env`, `*env*`, `.env.*`, `*.local`, `{.env,a}`) are still blocked.

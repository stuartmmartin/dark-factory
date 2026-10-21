@AGENTS.md

## Claude Code specifics
- Hooks (`.claude/settings.json` → `tools/agentkit/hook.sh` → `sb-agentkit hook …`):
  - they block secret and guardrail edits and edits to merged migrations;
  - they block reading `.env`, force-pushes, `--no-verify` and `core.hooksPath` overrides;
  - they run ruff and pyright on every edited Python file;
  - when you stop, they re-check guardrails (`guardrail-diff`) and run `make check-fast`, skipped
    when nothing changed since the last pass (a human can launch with `SB_STOP_CHECK=0` to skip it).
  If a hook blocks you, read its message and follow it. Never try to get around it.
- Skills: `tdd` (always, for code), `spec` (before non-trivial work), `adversarial-rca`
  (bugs/incidents). Once per branch, before it goes into `main`: `tighten`, `harvest` (when
  `.work/` has working docs), then `code-review`. Also `security-review`, `performance-review`,
  `supply-chain-audit`, `external-io` (reference).
- Subagents keep your context clean. Use `explorer` for "where is / who calls" questions, and
  `code-reviewer` through the `code-review` skill. Reviewers are read-only.
- Commands: `/review`, `/security-review`, `/spec`.
- The hooks run from this checkout's `.venv`, else the main checkout's. With neither they are
  inactive, and the session-start hook prints a WARNING. If you see it, run `make bootstrap`.

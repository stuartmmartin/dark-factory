#!/bin/sh
# Launch `sb-agentkit hook <name>` for .claude/settings.json. Uses this checkout's .venv, else the
# main checkout's, so a new worktree is guarded before (or without) its own `make bootstrap`.
# `hook.sh --check` (SessionStart) only warns when neither exists; it never blocks.
root=${CLAUDE_PROJECT_DIR:-.}
bin="$root/.venv/bin/sb-agentkit"
if [ ! -x "$bin" ]; then
  common=$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  [ -n "$common" ] && bin="$(dirname "$common")/.venv/bin/sb-agentkit"
fi
if [ "$1" = --check ]; then
  [ -x "$bin" ] || echo "WARNING: dark-factory agent hooks are INACTIVE (no .venv here or in the main checkout). Run make bootstrap."
  exit 0
fi
exec "$bin" hook "$@"

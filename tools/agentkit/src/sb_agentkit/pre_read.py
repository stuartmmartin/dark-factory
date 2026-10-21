"""PreToolUse guard for Read/Grep/Glob: block secret files. No override, unlike guardrail edits.

Guardrail files and migrations stay readable -- only live secrets are blocked, reusing the
shared secret patterns (`sb_agentkit.guardrails`) and the symlink-resolving, per-repo path views
(`target_views`). Grep's `path`/`glob` and Glob's `path`/`pattern` are checked too: a search
whose file filter names a `.env*` file reads it just as surely as `Read` does. Grep's own
`pattern` is a content regex, not a path, so searching the code FOR the text `.env` is allowed.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from sb_agentkit.guardrails import SECRET_EXCEPTIONS, is_secret, matches_pattern
from sb_agentkit.hookio import Decision, HookInput
from sb_agentkit.paths import target_views

_SECRET_SAMPLES = (".env", ".env.local", ".env.production", "x/.env")
# Pure wildcards, when they are the last path component (whatever the directory prefix).
_PURE_WILDCARDS = frozenset({"*", "**", "*.*"})
_BRACES = re.compile(r"\{([^{}]*)\}")
GLOB_KEYS = {"Grep": ("glob",), "Glob": ("pattern",)}


def _expand_braces(glob: str) -> list[str]:
    """`a{b,c}d` -> [`abd`, `acd`]; innermost groups first, so nested braces expand too."""
    match = _BRACES.search(glob)
    if match is None:
        return [glob]
    head, tail = glob[: match.start()], glob[match.end() :]
    return [e for alt in match.group(1).split(",") for e in _expand_braces(f"{head}{alt}{tail}")]


def _glob_names_secret(glob: str) -> bool:
    """Could this file glob match a secret? A pure-wildcard last component (`*`, `**`, `*.*`, under
    any directory prefix) is fine. Anything else is judged by its last component: it is a secret
    name itself, or (as a pattern) it matches a sample secret name. So `.env*`, `*.env`, `?env`,
    `*env*`, `*.local` and `{.env,a}` are blocked, while `*.py` and `.env.example` are not."""
    for candidate in _expand_braces(glob):
        last = PurePosixPath(candidate.casefold()).name
        if (
            not last
            or last in _PURE_WILDCARDS
            or matches_pattern(PurePosixPath(last), SECRET_EXCEPTIONS)
        ):
            continue
        if is_secret(PurePosixPath(last)):
            return True
        if any(fnmatchcase(sample, last) for sample in _SECRET_SAMPLES):
            return True
    return False


def _deny(what: str) -> Decision:
    return Decision.deny(
        f"{what} holds live secrets and must never be read by an agent. "
        "Use .env.example for the list of keys (C14)."
    )


def check_pre_read(inp: HookInput, root: Path) -> Decision:
    for _, rel in target_views(inp.target(), root):
        if is_secret(rel):
            return _deny(str(rel))
    for key in GLOB_KEYS.get(inp.tool_name, ()):
        glob = inp.text(key)
        if glob and _glob_names_secret(glob):
            return _deny(f"{inp.tool_name} {key} {glob!r}")
    return Decision.allow()

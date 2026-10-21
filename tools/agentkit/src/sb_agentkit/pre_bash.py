"""PreToolUse guard for Bash: protect secrets, shared history and the git hooks.

Raw tools (pytest, alembic, docker compose, psql) are allowed: make targets are the documented
shortcuts, not a fence. Only what is hard to undo is blocked: reading `.env`, force-pushes,
`--no-verify` and `core.hooksPath` overrides.

The command is tokenized the way a shell would (`shlex` with punctuation characters), so a
quoted `;`, `|` or `&&` stays argument text while real operators, subshell parentheses and
newlines separate commands. Wrappers (`env`, `timeout`, `sudo`, `xargs`, `uv run`, ...) are
peeled off, and `bash -c "<string>"` is checked recursively. If the command cannot be
tokenized at all (an unterminated quote), a conservative regex scan of the raw string still
blocks the high-risk patterns: `--no-verify`, force-pushes, hooks-path overrides, `.env` reads.

Documented blind spot: this guard does not evaluate backtick substitution, `eval`, or variable
expansion of a command name, so a command hidden behind one of those is not caught. See
``TestDocumentedBlindSpots`` in the test suite. Anything that slips through still meets the
Stop hook (`make check-fast`, `guardrail-diff`) and CI.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from sb_agentkit.hookio import Decision, HookInput

_PUNCTUATION = "();<>|&\n"
_SEPARATOR_CHARS = frozenset(";&|()\n")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"^python[0-9.]*$")
_READERS = frozenset(
    {"cat", "less", "more", "head", "tail", "grep", "rg", "bat", "sed", "awk"}
    | {"source", ".", "cp", "base64", "xxd", "od"}
)
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
# Wrapper -> its options that take a separate value. Other leading `-x` options are skipped.
_WRAPPERS: dict[str, frozenset[str]] = {
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "time": frozenset({"-f", "-o"}),
    "env": frozenset({"-u", "-C", "--unset", "--chdir"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "--user"}),
    "xargs": frozenset({"-I", "-i", "-n", "-P", "-L", "-l", "-s", "-d", "-E", "-e", "-a"}),
    "uvx": frozenset({"--from", "--with", "--python", "-p", "--index", "--directory"}),
}
_POSITIONAL_AFTER_OPTIONS = frozenset({"timeout"})  # `timeout 60 cmd`: skip the duration
_UV_RUN_VALUE_OPTS = frozenset(
    {"--package", "--with", "--with-editable", "--with-requirements", "--python", "-p"}
    | {"--directory", "--project", "--extra", "--group", "--only-group", "--env-file"}
    | {"--index", "--default-index", "--index-url", "--extra-index-url", "--no-group"}
)
_GIT_SUBCOMMANDS = ("push", "commit")
_COMMIT_VALUE_FLAGS = frozenset("mFCctuS")  # a short flag taking a value ends the bundle
# Only these consume the NEXT token; `-S[keyid]` and `-u[mode]` take an attached value only.
_COMMIT_NEXT_ARG_FLAGS = frozenset("mFCct")
_COMMIT_LONG_VALUE_FLAGS = frozenset(
    {"--message", "--file", "--author", "--date", "--reuse-message", "--reedit-message"}
    | {"--template"}
)
# `git config` options whose value is the next token (never the key).
_CONFIG_VALUE_OPTS = frozenset({"-f", "--file", "--blob", "--type", "--default"})
_HOOKS_PATH = "core.hookspath"
_PUSH_VALUE_FLAGS = frozenset("o")
_MAX_DEPTH = 4

# Fallback when the command cannot be tokenized (e.g. an unterminated quote).
_RAW_HIGH_RISK = (
    re.compile(r"--no-verify\b"),
    re.compile(r"\bpush\b.*(?:--force|\s-f\b|\s\+\S)"),
    re.compile(r"core\.hookspath", re.IGNORECASE),
    re.compile(r"(?:^|[\s/<'\"=])\.env(?!\.example\b)(?:\.[\w.-]+)?(?=$|[\s'\";|&)])", re.I),
)

_ENV_READ_MESSAGE = (
    "Reading .env files is blocked: they hold live secrets (C14). "
    "Use .env.example for the list of keys."
)


def _basename(word: str) -> str:
    return PurePosixPath(word).name or word  # `.` (source) has an empty PurePosixPath name


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"  # newline is an operator, not whitespace
    lexer.commenters = ""  # `a#b` is a word in bash; never let `#` hide the rest of the line
    return list(lexer)


def _is_separator(token: str) -> bool:
    return bool(token) and set(token) <= _SEPARATOR_CHARS


def split_segments(command: str) -> list[list[str]]:
    """Split a command into the argv of each simple command. Raises ValueError if unparseable."""
    segments: list[list[str]] = []
    current: list[str] = []
    for token in _tokens(command):
        if _is_separator(token):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _skip_options(args: list[str], value_opts: frozenset[str]) -> list[str]:
    """Drop leading `-x`/`--x` options (and the values of `value_opts`); stop after `--`."""
    rest = list(args)
    while rest and rest[0].startswith("-") and rest[0] != "-":
        option = rest.pop(0)
        if option == "--":
            break
        if option in value_opts and rest:
            rest.pop(0)
    return rest


def _strip_uv_run(rest: list[str]) -> list[str] | None:
    """`uv [global opts] run [opts] [--] cmd ...` -> `[cmd, ...]`; None if not `uv run`."""
    if "run" not in rest[1:]:
        return None
    return _skip_options(rest[rest.index("run", 1) + 1 :], _UV_RUN_VALUE_OPTS)


def _strip_wrapper(head: str, rest: list[str]) -> list[str]:
    stripped = _skip_options(rest[1:], _WRAPPERS[head])
    if head == "env":
        while stripped and _ENV_ASSIGNMENT.match(stripped[0]):
            stripped = stripped[1:]
    if head in _POSITIONAL_AFTER_OPTIONS and stripped:
        stripped = stripped[1:]
    return stripped


def _program(words: list[str]) -> list[str]:
    """Strip env assignments and wrappers (env, timeout, sudo, xargs, uv run, ...)
    -- including each wrapper's own options -- so the real program comes first, reduced to a
    basename so a full or relative path to the binary (/usr/bin/git) is still recognized.
    """
    rest = list(words)
    while rest:
        while rest and _ENV_ASSIGNMENT.match(rest[0]):
            rest = rest[1:]
        if not rest:
            break
        head = _basename(rest[0])
        stripped: list[str] | None = None
        if head in _WRAPPERS:
            stripped = _strip_wrapper(head, rest)
        elif head == "uv":
            stripped = _strip_uv_run(rest)
        if stripped is None:
            break
        rest = stripped
    if rest:
        rest = [_basename(rest[0]), *rest[1:]]
    return rest


def _is_secret(word: str) -> bool:
    name = PurePosixPath(word).name.casefold()
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def _find_subcommand(args: list[str], names: tuple[str, ...]) -> tuple[str | None, list[str]]:
    """Find the first argument that is EXACTLY one of `names` (the subcommand).

    Global options come in too many shapes to enumerate (`-H tcp://h`, `--log-level debug`,
    `--exec-path /x`, ...), so instead of trying to parse and skip them, scan past them: an
    exact-token match can't be spoofed by an option's own value (e.g. `commit.gpgsign=false`
    is not equal to `commit`).
    """
    for index, token in enumerate(args):
        if token in names:
            return token, args[index + 1 :]
    return None, []


def _short_bundle_has(token: str, flag: str, value_flags: frozenset[str]) -> bool:
    """Does a short-option bundle like `-anm` contain `flag` before a value-taking flag?"""
    if not token.startswith("-") or token.startswith("--"):
        return False
    for char in token[1:]:
        if char == flag:
            return True
        if char in value_flags:
            return False
    return False


def _bundle_takes_next_arg(token: str, value_flags: frozenset[str]) -> bool:
    """Is `token` a short-option bundle ending in a value-taking flag (`-m`, `-am`), so that the
    NEXT argument is that flag's value?"""
    if not token.startswith("-") or token.startswith("--"):
        return False
    body = token[1:]
    for index, char in enumerate(body):
        if char in value_flags:
            return index == len(body) - 1
    return False


def _commit_skips_hooks(args: list[str]) -> bool:
    """`--no-verify` or a `-n` in a short bundle, ignoring the values of value-taking flags."""
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
        elif arg == "--no-verify":
            return True
        elif arg in _COMMIT_LONG_VALUE_FLAGS:
            skip_next = True
        elif arg.startswith("--"):
            continue
        elif _short_bundle_has(arg, "n", _COMMIT_VALUE_FLAGS):
            return True
        elif _bundle_takes_next_arg(arg, _COMMIT_NEXT_ARG_FLAGS):
            skip_next = True
    return False


def _config_key_is_hooks_path(sub_args: list[str]) -> bool:
    """Any `git config` argument that IS the hooks-path key, skipping option values."""
    skip_next = False
    for arg in sub_args:
        if skip_next:
            skip_next = False
        elif arg in _CONFIG_VALUE_OPTS:
            skip_next = True
        elif arg.casefold() == _HOOKS_PATH:
            return True
    return False


def _sets_hooks_path(rest: list[str]) -> bool:
    """The hooks-path key matters as `-c key=value`, `--config-env=key=ENV`, or a `git config`
    argument -- not as text in a commit message or a `git grep` pattern."""
    for index, word in enumerate(rest):
        following = rest[index + 1] if index + 1 < len(rest) else ""
        value = None
        if word in ("-c", "--config-env"):
            value = following
        elif word.startswith("--config-env="):
            value = word.split("=", 1)[1]
        if value is not None and value.split("=", 1)[0].casefold() == _HOOKS_PATH:
            return True
    sub, sub_args = _find_subcommand(rest, ("config",))
    return sub == "config" and _config_key_is_hooks_path(sub_args)


def _check_git(rest: list[str]) -> Decision:
    if _sets_hooks_path(rest):
        return Decision.deny("Redirecting git hooks (core.hooksPath) is not allowed.")
    sub, sub_args = _find_subcommand(rest, _GIT_SUBCOMMANDS)
    if sub == "push" and any(
        a == "--force"
        or a.startswith(("--force-with-lease", "+"))
        or _short_bundle_has(a, "f", _PUSH_VALUE_FLAGS)
        for a in sub_args
    ):
        return Decision.deny("Force-pushing rewrites shared history; it is never done by agents.")
    if sub == "commit" and _commit_skips_hooks(sub_args):
        return Decision.deny("Skipping git hooks is not allowed; fix what the hooks report.")
    return Decision.allow()


def _shell_string(head: str, rest: list[str]) -> str | None:
    """The command string of `bash -c "<str>"` (also `-lc`, `-ec`, ...), else None."""
    if head not in _SHELLS:
        return None
    for index, arg in enumerate(rest):
        if not arg.startswith("-") or arg.startswith("--"):
            return None
        if "c" in arg[1:]:
            return rest[index + 1] if index + 1 < len(rest) else None
    return None


def _check_segment(words: list[str], depth: int) -> Decision:
    program = _program(words)
    if not program:
        return Decision.allow()
    head, rest = program[0], program[1:]
    nested = _shell_string(head, rest)
    if nested is not None:
        return _check_command(nested, depth + 1)
    if (head in _READERS or _PYTHON.match(head)) and any(_is_secret(arg) for arg in rest):
        return Decision.deny(_ENV_READ_MESSAGE)
    if head == "git":
        return _check_git(rest)
    return Decision.allow()


def _check_raw(command: str) -> Decision:
    for pattern in _RAW_HIGH_RISK:
        if pattern.search(command):
            return Decision.deny(
                "This command could not be parsed, and it contains a blocked pattern "
                "(--no-verify, a force-push, a hooks-path override or a .env read). "
                "Fix the quoting, and do not bypass hooks, rewrite history or read secrets. "
                + _ENV_READ_MESSAGE
            )
    return Decision.allow()


def _check_command(command: str, depth: int) -> Decision:
    if depth > _MAX_DEPTH:
        return _check_raw(command)
    try:
        segments = split_segments(command)
    except ValueError:
        return _check_raw(command)
    for words in segments:
        decision = _check_segment(words, depth)
        if decision.block:
            return decision
    return Decision.allow()


def check_pre_bash(inp: HookInput) -> Decision:
    return _check_command(inp.text("command"), depth=0)

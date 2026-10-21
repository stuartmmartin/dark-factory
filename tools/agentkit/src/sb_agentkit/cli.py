"""``sb-agentkit``: hook entry points (read Claude Code JSON on stdin) and repo agent tooling."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import TextIO

from sb_agentkit.guardrail_diff import GitError, changed_guardrails
from sb_agentkit.hookio import Decision, HookInput, emit
from sb_agentkit.lint_docs import lint
from sb_agentkit.paths import repo_root_for
from sb_agentkit.post_edit import check_post_edit
from sb_agentkit.pre_bash import check_pre_bash
from sb_agentkit.pre_edit import GitBaseRef, check_pre_edit
from sb_agentkit.pre_read import check_pre_read
from sb_agentkit.review_result import FOCUSES
from sb_agentkit.review_result import main as review_result_main
from sb_agentkit.runner import subprocess_runner
from sb_agentkit.session_base import ensure_session_base
from sb_agentkit.stop import check_stop
from sb_agentkit.triage import matrix_json, reviewers_for

__all__ = ["main"]

GUARDED_BEFORE_TOOL = ("pre-edit", "pre-bash", "pre-read")  # first call records the baseline
HOOKS = ("pre-edit", "pre-bash", "pre-read", "post-edit", "stop")


def _repo_root(cwd: Path) -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env_root) if env_root else cwd


def _run_hook(name: str, stdin: TextIO) -> int:
    cwd = Path.cwd()
    inp = HookInput.parse(stdin.read(), default_cwd=cwd)
    if inp is None:
        print(f"sb-agentkit hook {name}: unreadable hook payload; allowing", file=sys.stderr)
        return 0
    root = _repo_root(inp.cwd)  # the fallback; each hook resolves the repo owning its target
    decision = Decision.allow()
    if name in GUARDED_BEFORE_TOOL:
        ensure_session_base(repo_root_for(inp.cwd, root), inp.session_id)
    if name == "pre-edit":
        decision = check_pre_edit(inp, root, GitBaseRef(), os.environ)
    elif name == "pre-bash":
        decision = check_pre_bash(inp)
    elif name == "pre-read":
        decision = check_pre_read(inp, root)
    elif name == "post-edit":
        decision = check_post_edit(inp, root, subprocess_runner)
    elif name == "stop":
        decision = check_stop(inp, root, subprocess_runner, os.environ)
    return emit(decision, sys.stderr, sys.stdout, event=inp.event)


def _run_lint(root: Path) -> int:
    problems = lint(root)
    for problem in problems:
        print(problem)
    if problems:
        print(f"sb-agentkit lint: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("sb-agentkit lint: ok", file=sys.stderr)
    return 0


def _run_review_triage(base: str, root: Path) -> int:
    result = subprocess_runner(["git", "diff", "--name-only", f"{base}...HEAD"], root)
    if result.returncode != 0:
        print(f"sb-agentkit: git diff failed for base {base}: {result.output}", file=sys.stderr)
        return 2
    paths = (PurePosixPath(line) for line in result.output.splitlines() if line)
    print(matrix_json(reviewers_for(paths)))
    return 0


def _run_guardrail_diff(base: str | None, root: Path) -> int:
    try:
        paths = changed_guardrails(root, base, env=os.environ)
    except GitError as exc:
        print(f"sb-agentkit guardrail-diff: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 1 if paths else 0


def main(argv: Sequence[str] | None = None, stdin: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sb-agentkit", description="Agent scaffolding tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="Run a Claude Code hook (reads JSON on stdin).")
    hook.add_argument("name", choices=HOOKS)
    lint_parser = sub.add_parser("lint", help="Lint agent docs (frontmatter, rule IDs, links).")
    lint_parser.add_argument("--root", type=Path, default=Path.cwd())
    triage_parser = sub.add_parser(
        "review-triage", help="Print the AI-review matrix for paths changed since --base."
    )
    triage_parser.add_argument("--base", required=True)
    triage_parser.add_argument("--root", type=Path, default=Path.cwd())
    diff_parser = sub.add_parser(
        "guardrail-diff",
        help="List guardrail files changed vs the merge-base with --base (default origin/main, "
        "else main), not covered by SB_ALLOW_GUARDRAIL_EDITS. Exit 1 if any.",
    )
    diff_parser.add_argument("--base", default=None)
    diff_parser.add_argument("--root", type=Path, default=Path.cwd())
    result_parser = sub.add_parser(
        "review-result", help="Validate evidence and print PASS/FAIL/BLOCKED (not an exit gate)."
    )
    result_parser.add_argument("path", type=Path)
    result_parser.add_argument("--focus", choices=FOCUSES, required=True)
    result_parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    if args.command == "review-result":
        return review_result_main(
            [
                str(args.path),
                "--focus",
                args.focus,
                "--commit",
                args.commit,
            ]
        )
    if args.command == "lint":
        return _run_lint(args.root)
    if args.command == "review-triage":
        return _run_review_triage(args.base, args.root)
    if args.command == "guardrail-diff":
        return _run_guardrail_diff(args.base, args.root)
    return _run_hook(args.name, stdin or sys.stdin)

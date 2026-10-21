"""Command line entry point for the build graph: ``sb-graph <command>``."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sb_graph.affected import GitError, affected_members, changed_files
from sb_graph.coverage import coverage_errors
from sb_graph.graph import Graph, GraphError, load_graph, validate
from sb_graph.render import GENERATED_DIR, generated_files
from sb_graph.service_contracts import service_contract_errors
from sb_graph.workspace import Member, WorkspaceError

__all__ = ["main"]

FORMATS = ("names", "paths", "json", "imports")
MAX_DIFF_LINES = 40


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb-graph", description="Workspace build graph.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help=f"Write {GENERATED_DIR}/*.")
    sub.add_parser(
        "check",
        help="Fail if generated files are stale, deps disagree, or root configs miss a member.",
    )
    members = sub.add_parser("members", help="List workspace members.")
    members.add_argument("--format", choices=FORMATS, default="names")
    members.add_argument("--kind", choices=("lib", "service", "tool", "app"))
    affected = sub.add_parser("affected", help="Members affected by changes since --base.")
    affected.add_argument("--base", default="origin/main", help="Base ref (default origin/main).")
    affected.add_argument("--no-worktree", action="store_true", help="Ignore uncommitted files.")
    affected.add_argument("--format", choices=FORMATS, default="names")
    blast = sub.add_parser("blast-radius", help="Members that depend on MEMBER, transitively.")
    blast.add_argument("member")
    deps = sub.add_parser("deps", help="Members MEMBER depends on, transitively.")
    deps.add_argument("member")
    return parser


def _matrix_entry(member: Member) -> dict[str, str]:
    """One GitHub matrix row. `name` is the normalized (hyphenated) distribution name: the image
    and the k8s directory (`deploy/k8s/<name>/`). `path` is the member directory (its
    Dockerfile), and `import_name` the Python package (the Dockerfile's SERVICE build-arg)."""
    return {"name": member.name, "path": str(member.path), "import_name": member.import_name}


def print_members(members: Sequence[Member], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps({"include": [_matrix_entry(m) for m in members]}))
        return
    for member in members:
        value = member.import_name if fmt == "imports" else member.path
        print(member.name if fmt == "names" else value)


def _check(root: Path, graph: Graph) -> int:
    problems = (
        validate(root, graph) + coverage_errors(root, graph) + service_contract_errors(root, graph)
    )
    for path, content in generated_files(root, graph).items():
        target = root / path
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != content:
            problems.append(f"{path} is stale; run `make graph` and commit the result")
            diff = difflib.unified_diff(
                current.splitlines(),
                content.splitlines(),
                "committed",
                "generated",
                lineterm="",
                n=1,
            )
            problems.extend(f"    {line}" for line in list(diff)[:MAX_DIFF_LINES])
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("sb-graph: build graph up to date")
    return 0


def _generate(root: Path, graph: Graph) -> int:
    for path, content in generated_files(root, graph).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"wrote {path}")
    return 0


def _affected(args: argparse.Namespace, root: Path, graph: Graph) -> int:
    try:
        changed = changed_files(root, args.base, include_worktree=not args.no_worktree)
    except GitError as exc:
        print(f"sb-graph: {exc}", file=sys.stderr)
        return 2
    names = affected_members(graph, changed)
    print_members([graph.member(name) for name in names], args.format)
    return 0


def _dispatch(args: argparse.Namespace, root: Path, graph: Graph) -> int:
    if args.command == "generate":
        return _generate(root, graph)
    if args.command == "check":
        return _check(root, graph)
    if args.command == "affected":
        return _affected(args, root, graph)
    if args.command == "blast-radius":
        print("\n".join(graph.dependents_closure(args.member)))
        return 0
    if args.command == "deps":
        print("\n".join(graph.deps_closure(args.member)))
        return 0
    print_members(
        [m for m in graph.members if args.kind is None or m.kind == args.kind], args.format
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root: Path = args.root.resolve()
    try:
        return _dispatch(args, root, load_graph(root))
    except (WorkspaceError, GraphError) as exc:
        print(f"sb-graph: {exc}", file=sys.stderr)
        return 2

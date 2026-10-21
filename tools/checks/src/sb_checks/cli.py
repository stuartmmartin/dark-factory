"""Command line entry point: ``run``, ``list``, ``doctor``, ``openapi`` and ``doc-commands``."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sb_checks import doc_commands, openapi
from sb_checks.allowlist import ALLOWLIST_PATH, AllowlistError, load_allowlist
from sb_checks.checks import ALL_CHECKS
from sb_checks.doctor import DEFAULT_COMPOSE, Probe, SystemProbe, diagnose
from sb_checks.runner import run_checks

__all__ = ["ALL_CHECKS", "main"]


def main(argv: Sequence[str] | None = None, probe: Probe | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sb-checks", description="AST convention checks.")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Run every check over libs/, services/, tools/.")
    run_parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    sub.add_parser("list", help="List the available checks.")
    doctor_parser = sub.add_parser("doctor", help="Diagnose the local environment.")
    doctor_parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    doctor_parser.add_argument(
        "--compose",
        default=DEFAULT_COMPOSE,
        help="Compose command prefix (as the Makefile runs it).",
    )
    openapi_parser = sub.add_parser(
        "openapi", help="Write or drift-check a service's contracts/openapi/<service>.json."
    )
    openapi_parser.add_argument("--service", required=True, help="Service package, e.g. ledger.")
    openapi_parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    mode = openapi_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if the contract has drifted.")
    mode.add_argument("--write", action="store_true", help="Write the contract.")
    docs_parser = sub.add_parser(
        "doc-commands", help="Print (or --run) a doc's `sh env-setup` blocks."
    )
    docs_parser.add_argument("file", type=Path, help="Markdown file.")
    docs_parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    docs_parser.add_argument("--run", action="store_true", help="Execute the blocks in order.")
    args = parser.parse_args(argv)

    if args.command == "list":
        for check in ALL_CHECKS:
            print(f"{check.check_id}: {check.description}")
        return 0

    root: Path = args.root.resolve()
    handlers: dict[str, Callable[[], int]] = {
        "doctor": lambda: _doctor(args.compose, probe or SystemProbe(root)),
        "openapi": lambda: _openapi(root, args.service, write=args.write),
        "doc-commands": lambda: _doc_commands(root, args.file, run=args.run),
    }
    if args.command in handlers:
        return handlers[args.command]()
    try:
        allowlist = load_allowlist(root / ALLOWLIST_PATH)
    except AllowlistError as exc:
        print(f"sb-checks: {exc}", file=sys.stderr)
        return 2
    violations = run_checks(root, ALL_CHECKS, allowlist)
    for violation in violations:
        print(violation.render())
    if violations:
        print(
            f"\n{len(violations)} violation(s). Fix the code; exemptions live in "
            f"{ALLOWLIST_PATH} (human-owned, reason required).",
            file=sys.stderr,
        )
        return 1
    print(f"sb-checks: {len(ALL_CHECKS)} checks, 0 violations")
    return 0


def _doctor(compose: str, probe: Probe) -> int:
    marks = {"ok": "✔", "warn": "!", "fail": "✘"}
    findings = diagnose(probe, os.environ, compose)
    for finding in findings:
        print(f"{marks[finding.status]} {finding.name} — {finding.detail}")
    return 1 if any(f.status == "fail" for f in findings) else 0


def _openapi(root: Path, service: str, *, write: bool) -> int:
    try:
        if write:
            print(f"sb-checks: wrote {openapi.write(root, service).relative_to(root)}")
            return 0
        problem = openapi.check(root, service)
    except openapi.ServiceNameError as exc:
        print(f"sb-checks: {exc}", file=sys.stderr)
        return 2
    if problem is not None:
        print(f"sb-checks openapi: {problem}", file=sys.stderr)
        return 1
    print(f"sb-checks openapi: {service} matches {openapi.CONTRACTS_DIR / service}.json")
    return 0


def _doc_commands(root: Path, file: Path, *, run: bool) -> int:
    try:
        blocks = doc_commands.extract(file.read_text())
    except doc_commands.DocError as exc:
        print(f"sb-checks doc-commands: {file}: {exc}", file=sys.stderr)
        return 1
    if not blocks:
        print(
            f"sb-checks doc-commands: no `sh {doc_commands.DEFAULT_TAG}` blocks in {file}",
            file=sys.stderr,
        )
        return 1
    if not run:
        print("\n".join(blocks), end="")
        return 0
    try:
        failed = doc_commands.run(
            blocks, root, announce=_announce_block, timeout=doc_commands.BLOCK_TIMEOUT_SECONDS
        )
    except doc_commands.BlockTimeoutError as exc:
        print(f"sb-checks doc-commands: {exc}", file=sys.stderr)
        return 1
    if failed is None:
        print(f"sb-checks doc-commands: all {len(blocks)} blocks passed")
        return 0
    print(f"sb-checks doc-commands: block {failed} of {len(blocks)} failed", file=sys.stderr)
    return 1


def _announce_block(number: int, total: int, block: str) -> None:
    print(f"==> block {number} of {total}\n{block}", flush=True)

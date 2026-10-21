"""Validate versioned, commit-bound reviewer evidence and derive the CI gate verdict.

All requested focuses fail closed on missing or malformed evidence. A reviewer's PASS cannot
waive a blocking finding. A declared FAIL/BLOCKED is never promoted to PASS automatically.
This validates the evidence shape, not the truth of an LLM's claims or its resistance to injection.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import cast

FOCUSES = ("security", "architecture", "engineering", "all")
VERDICTS = frozenset({"PASS", "FAIL", "BLOCKED"})
RESULT_FIELDS = frozenset({"schema_version", "commit", "focus", "verdict", "findings"})
FINDING_FIELDS = frozenset({"rule", "severity", "path", "line", "quote", "fix"})
MAX_RESULT_BYTES = 1_000_000


def _mapping(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    data = cast(dict[str, object], value)
    if data.keys() != fields:
        raise ValueError(f"expected exactly these fields: {', '.join(sorted(fields))}")
    return data


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected a non-empty string")
    return value


def _finding(value: object) -> bool:
    finding = _mapping(value, FINDING_FIELDS)
    for key in ("rule", "severity", "path", "quote", "fix"):
        _text(finding[key])
    severity = finding["severity"]
    if severity not in ("blocking", "advisory"):
        raise ValueError("finding severity must be blocking or advisory")
    line = finding["line"]
    if type(line) is not int or line < 1:
        raise ValueError("finding line must be a positive integer")
    path = PurePosixPath(_text(finding["path"]))
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in str(path):
        raise ValueError("finding path must be repository-relative")
    return severity == "blocking"


def validated_verdict(value: object, focus: str, commit: str) -> str:
    """Return PASS/FAIL/BLOCKED, or raise ValueError for invalid/inapplicable evidence."""
    data = _mapping(value, RESULT_FIELDS)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported review-result schema_version (expected 1)")
    if focus not in FOCUSES or data["focus"] != focus:
        raise ValueError("review focus does not match the requested reviewer")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or data["commit"] != commit:
        raise ValueError("review commit does not match the checked-out commit")
    declared = _text(data["verdict"])
    if declared not in VERDICTS:
        raise ValueError("invalid review verdict")
    findings = data["findings"]
    if not isinstance(findings, list):
        raise ValueError("findings must be an array")
    # Validate ALL findings, not just until the first blocking finding.
    blocking = [_finding(item) for item in cast(list[object], findings)]
    if declared == "BLOCKED":
        return "BLOCKED"
    return "FAIL" if any(blocking) or declared == "FAIL" else "PASS"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_verdict(path: Path, focus: str, commit: str) -> str:
    """Read bounded JSON evidence; reject duplicate keys and wrong commit/focus/schema."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("review result exceeds the size limit")
    value: object = json.loads(raw, object_pairs_hook=_unique_object)
    return validated_verdict(value, focus, commit)


def main(argv: Sequence[str] | None = None) -> int:
    """Print a gate decision, not an exit gate; usable without installing PR dependencies."""
    parser = argparse.ArgumentParser(description="Validate commit-bound review evidence.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--focus", choices=FOCUSES, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        verdict = read_verdict(args.path, args.focus, args.commit)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"invalid review evidence: {exc}", file=sys.stderr)  # noqa: T201 - CI validator CLI
        verdict = "BLOCKED"
    print(verdict)  # noqa: T201 - CI consumes the normalized gate decision from stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

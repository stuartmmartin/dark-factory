"""The machine, not the reviewer's self-reported verdict, enforces blocking findings."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sb_agentkit.cli import main
from sb_agentkit.review_result import MAX_RESULT_BYTES, validated_verdict

COMMIT = "a" * 40


def result(verdict: str = "PASS", severity: str | None = None) -> dict[str, Any]:
    findings = (
        []
        if severity is None
        else [
            {
                "rule": "T2",
                "severity": severity,
                "path": "services/ledger/src/ledger/main.py",
                "line": 1,
                "quote": "new_behavior()",
                "fix": "Add a meaningful behavior test.",
            }
        ]
    )
    return {
        "schema_version": 1,
        "commit": COMMIT,
        "focus": "engineering",
        "verdict": verdict,
        "findings": findings,
    }


@pytest.mark.parametrize(
    ("declared", "severity", "expected"),
    [
        ("PASS", None, "PASS"),
        ("PASS", "advisory", "PASS"),
        ("PASS", "blocking", "FAIL"),
        ("FAIL", "blocking", "FAIL"),
        ("FAIL", "advisory", "FAIL"),
        ("BLOCKED", None, "BLOCKED"),
    ],
)
def test_verdict_cannot_override_blocking_findings(declared, severity, expected) -> None:
    assert validated_verdict(result(declared, severity), "engineering", COMMIT) == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("commit", "b" * 40),
        ("focus", "security"),
        ("verdict", "pass"),
        ("findings", None),
        ("findings", [{}]),
        ("unexpected", True),
    ],
)
def test_invalid_evidence_is_rejected(key, value) -> None:
    evidence = result()
    evidence[key] = value
    with pytest.raises(ValueError, match=r"schema|commit|focus|verdict|array|fields|object"):
        validated_verdict(evidence, "engineering", COMMIT)


@pytest.mark.parametrize(
    ("focus", "commit", "error"),
    [
        ("unknown", COMMIT, "focus"),
        ("engineering", "not-a-commit", "commit"),
        ("engineering", "A" * 40, "commit"),
        ("engineering", "a" * 39, "commit"),
    ],
)
def test_matching_but_invalid_request_binding_is_rejected(focus, commit, error) -> None:
    # Matching strings are insufficient: the requested binding itself must be valid.
    evidence = result()
    evidence.update(focus=focus, commit=commit)
    with pytest.raises(ValueError, match=error):
        validated_verdict(evidence, focus, commit)


@pytest.mark.parametrize("key", list(result()))
def test_missing_required_field_is_rejected(key: str) -> None:
    evidence = result()
    del evidence[key]
    with pytest.raises(ValueError, match="expected exactly these fields"):
        validated_verdict(evidence, "engineering", COMMIT)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("severity", "warning"),
        ("line", 0),
        ("line", True),
        ("line", "1"),
        ("path", "../outside.py"),
        ("path", "."),
        ("path", "/absolute.py"),
        ("path", "a\\b.py"),
        ("quote", ""),
        ("fix", 5),
    ],
)
def test_invalid_finding_is_rejected(key, value) -> None:
    evidence = result(severity="blocking")
    finding = evidence["findings"][0]
    finding[key] = value
    with pytest.raises(ValueError, match=r"severity|line|path|string"):
        validated_verdict(evidence, "engineering", COMMIT)


@pytest.mark.parametrize("body", [None, "{", "[]", "null"])
def test_cli_emits_blocked_for_missing_or_malformed_result(tmp_path: Path, capsys, body) -> None:
    path = tmp_path / "review.json"
    if body is not None:
        path.write_text(body)
    assert main(["review-result", str(path), "--focus", "engineering", "--commit", COMMIT]) == 0
    output = capsys.readouterr()
    assert output.out.strip() == "BLOCKED"
    assert output.err


@pytest.mark.parametrize("invalid", ["duplicate", "oversized"])
def test_cli_rejects_ambiguous_or_oversized_evidence(tmp_path: Path, capsys, invalid: str) -> None:
    path = tmp_path / "review.json"
    body = json.dumps(result())
    if invalid == "duplicate":
        body = body.replace('"verdict": "PASS"', '"verdict": "FAIL", "verdict": "PASS"')
        expected = "duplicate JSON key"
    else:
        # Otherwise valid JSON: without the bounded read this would PASS.
        body += " " * MAX_RESULT_BYTES
        expected = "exceeds the size limit"
    path.write_text(body)
    assert main(["review-result", str(path), "--focus", "engineering", "--commit", COMMIT]) == 0
    output = capsys.readouterr()
    assert output.out.strip() == "BLOCKED"
    assert expected in output.err


def test_standalone_validator_needs_no_installed_packages(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps(result("PASS", "blocking")))
    script = Path(__file__).resolve().parents[1] / "src/sb_agentkit/review_result.py"
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(script),
            str(path),
            "--focus",
            "engineering",
            "--commit",
            COMMIT,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "FAIL"


def test_cli_derives_failure_from_findings(tmp_path: Path, capsys) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps(result("PASS", "blocking")))
    assert main(["review-result", str(path), "--focus", "engineering", "--commit", COMMIT]) == 0
    assert capsys.readouterr().out.strip() == "FAIL"

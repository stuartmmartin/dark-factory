import json
from pathlib import PurePosixPath

import pytest

from sb_agentkit.triage import Reviewer, matrix_json, reviewers_for


def _names(*paths: str) -> list[str]:
    return [r.name for r in reviewers_for(PurePosixPath(p) for p in paths)]


def test_docs_only_change_gets_no_review() -> None:
    assert _names("docs/README.md", "docs/adr/0001-x.md", "README.md") == []


def test_service_use_case_gets_security_architecture_and_engineering() -> None:
    assert _names("services/ledger/src/ledger/application/use_cases/post.py") == [
        "security",
        "architecture",
        "engineering",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "services/ledger/src/ledger/interface/http/routes.py",
        "services/ledger/migrations/versions/0002_x.py",
        "services/ledger/src/ledger/infrastructure/settings.py",
        "libs/py/sb_http/src/sb_http/auth.py",
        "libs/py/sb_db/src/sb_db/tenant.py",
        "libs/py/sb_admin/src/sb_admin/auth.py",
        "libs/py/sb_messaging/src/sb_messaging/inbox.py",
        "libs/py/sb_workflows/src/sb_workflows/client.py",
        "libs/py/sb_kernel/src/sb_kernel/context.py",
        "libs/py/sb_obs/src/sb_obs/redaction.py",
        "services/ledger/src/ledger/interface/workflows/activities.py",
        "services/ledger/src/ledger/interface/consumers/account_opened.py",
        "services/ledger/src/ledger/infrastructure/repositories.py",
        "services/ledger/src/ledger/application/policies/authorization.py",
        "services/ledger/src/ledger/bootstrap.py",
        "contracts/events/ledger.account.opened.v1.json",
        ".github/workflows/ci.yml",
        "services/ledger/Dockerfile",
        "deploy/k8s/ledger/base/deployment.yaml",
        "uv.lock",
    ],
)
def test_sensitive_paths_add_security(path: str) -> None:
    assert "security" in _names(path)


def test_boundary_config_gets_architecture() -> None:
    # .importlinter is also a guardrail, so it gets the security reviewer too (I4).
    assert _names(".importlinter") == ["security", "architecture", "engineering"]


def test_order_and_blocking_flags_are_stable() -> None:
    reviewers = reviewers_for([PurePosixPath("libs/py/sb_db/src/sb_db/uow.py")])
    assert reviewers == [
        Reviewer("security", True),
        Reviewer("architecture", True),
        Reviewer("engineering", True),
    ]


def test_matrix_json_shape() -> None:
    data = json.loads(matrix_json([Reviewer("security", True)]))
    assert data == {"include": [{"reviewer": "security", "blocking": True}]}
    assert json.loads(matrix_json([])) == {"include": []}


@pytest.mark.parametrize(
    "path",
    [
        "ruff.toml",
        "pyrightconfig.json",
        ".pre-commit-config.yaml",
        ".claude/settings.json",
        ".claude/skills/code-review/reviewer-prompt.md",
        ".claude/agents/security-reviewer.md",
        ".github/CODEOWNERS",
        ".github/scripts/check-override.sh",
        "docs/conventions/coding.md",
    ],
)
def test_guardrail_only_change_gets_blocking_review(path: str) -> None:
    """A PR that only loosens a guardrail must not slip through with no AI review at all."""
    names = _names(path)
    assert "security" in names
    assert "architecture" in names


def test_guardrail_patterns_match_case_insensitively() -> None:
    assert "security" in _names("RUFF.TOML")


def test_daily_work_non_code_change_still_gets_no_review() -> None:
    daily = ("Makefile", "mk/python.mk", "docs/agents/hooks.md", ".claude/rules/tests.md")
    assert _names(*daily) == []

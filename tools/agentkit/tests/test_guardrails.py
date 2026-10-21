from pathlib import Path, PurePosixPath

import pytest

from sb_agentkit.guardrails import (
    GUARDRAIL_PATTERNS,
    OVERRIDE_ENV,
    is_guardrail,
    is_secret,
    is_user_claude_config,
    override_allows,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
CODEOWNERS_SECTION = "# Human-owned guardrails"
# Guardrails CODEOWNERS cannot express: .git/ is never tracked, ~/.claude is outside the repo.
CODEOWNERS_EXEMPT = (".git/hooks/**", "~/.claude/**")


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.local.json",
        ".claude/skills/code-review/SKILL.md",
        ".claude/skills/code-review/reviewer-prompt.md",
        ".claude/agents/code-reviewer.md",
        ".github/pull_request_template.md",
        ".github/scripts/check-override.sh",
        ".git/hooks/pre-commit",
        "tools/checks/src/sb_checks/checks/no_float.py",
        "tools/agentkit/tests/test_pre_edit.py",
        "tools/agentkit/pyproject.toml",
        ".pre-commit-config.yaml",
        "conftest.py",
        "docs/conventions/coding.md",
        "ruff.toml",
        "pyrightconfig.json",
        "tach.toml",
        ".importlinter",
        "tools/checks/allowlist.toml",
        ".claude/settings.json",
        ".github/CODEOWNERS",
        ".github/workflows/ci.yml",
    ],
)
def test_guardrail_paths(path: str) -> None:
    assert is_guardrail(PurePosixPath(path))


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "Makefile",
        "mk/python.mk",
        "mk/contracts.mk",
        "mk/quality.mk",
        "tools/checks/tests/test_cli.py",
        ".claude/skills/tdd/SKILL.md",
        ".claude/rules/tests.md",
        "services/ledger/src/ledger/domain/entry.py",
        "docs/agents/hooks.md",
    ],
)
def test_daily_work_files_are_not_guardrails(path: str) -> None:
    assert not is_guardrail(PurePosixPath(path))


def test_secret_classification() -> None:
    assert is_secret(PurePosixPath("services/x/.env.local"))
    assert not is_secret(PurePosixPath(".env.example"))


def test_override_one_allows_everything() -> None:
    assert override_allows(PurePosixPath("tach.toml"), {OVERRIDE_ENV: "1"})


def test_no_override_allows_nothing() -> None:
    assert not override_allows(PurePosixPath("tach.toml"), {})
    assert not override_allows(PurePosixPath("tach.toml"), {OVERRIDE_ENV: ""})
    assert not override_allows(PurePosixPath("tach.toml"), {OVERRIDE_ENV: "0"})


@pytest.mark.parametrize(
    ("value", "path", "allowed"),
    [
        ("tach.toml", "tach.toml", True),
        ("tach.toml", ".importlinter", False),
        ("tach.toml, .importlinter", ".importlinter", True),
        (".github/workflows/**", ".github/workflows/ci.yml", True),
        (".github/workflows/**", ".github/CODEOWNERS", False),
        ("docs/conventions", "docs/conventions/coding.md", True),
        ("./ruff.toml", "ruff.toml", True),
        ("TACH.TOML", "tach.toml", True),
        (",,", "tach.toml", False),
    ],
)
def test_scoped_override_allows_only_listed_paths(value: str, path: str, allowed: bool) -> None:
    assert override_allows(PurePosixPath(path), {OVERRIDE_ENV: value}) is allowed


def test_user_claude_config_is_detected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    assert is_user_claude_config(home / ".claude" / "settings.json", home)
    assert is_user_claude_config(home / "x" / ".." / ".claude" / "hooks" / "a.sh", home)
    assert not is_user_claude_config(home / "project" / ".claude" / "settings.json", home)


def test_symlink_into_user_claude_config_is_detected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (tmp_path / "sneaky").symlink_to(home / ".claude")
    assert is_user_claude_config(tmp_path / "sneaky" / "settings.json", home)


def _codeowners_guardrail_entries(codeowners: Path = CODEOWNERS) -> list[str]:
    lines = codeowners.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(CODEOWNERS_SECTION))
    body = lines[start + 1 :]
    while body and body[0].startswith("#"):  # the header's own continuation lines
        body = body[1:]
    entries: list[str] = []
    for line in body:
        if not line.strip() or line.startswith("#"):
            break
        entries.append(line.split()[0])
    return entries


def test_codeowners_guardrail_section_is_not_empty() -> None:
    assert len(_codeowners_guardrail_entries()) >= 10


def test_every_codeowners_guardrail_is_guarded_by_the_hooks() -> None:
    """Parity: anything CODEOWNERS calls a human-owned guardrail, the hooks must also block."""
    unguarded: list[str] = []
    for entry in _codeowners_guardrail_entries():
        rel = entry.lstrip("/")
        sample = f"{rel}probe.txt" if rel.endswith("/") else rel
        if not is_guardrail(PurePosixPath(sample)):
            unguarded.append(entry)
    assert unguarded == []


def _guardrail_sample(pattern: str) -> str:
    return f"{pattern[:-2]}probe.txt" if pattern.endswith("/**") else pattern


def _codeowners_covers(entry: str, sample: str) -> bool:
    rel = entry.lstrip("/")
    return sample.startswith(rel) if rel.endswith("/") else sample == rel


def _unowned_guardrails(codeowners: Path = CODEOWNERS) -> list[str]:
    entries = _codeowners_guardrail_entries(codeowners)
    return [
        pattern
        for pattern in GUARDRAIL_PATTERNS
        if pattern not in CODEOWNERS_EXEMPT
        and not any(_codeowners_covers(e, _guardrail_sample(pattern)) for e in entries)
    ]


def test_every_guardrail_pattern_is_owned_in_codeowners() -> None:
    """Reverse parity: anything the hooks block, CODEOWNERS must also make owner-reviewed."""
    assert _unowned_guardrails() == []


def test_reverse_parity_goes_red_when_a_codeowners_line_is_removed(tmp_path: Path) -> None:
    """Mutation check on a COPY of CODEOWNERS (the real file is never touched)."""
    text = CODEOWNERS.read_text(encoding="utf-8")
    kept = [line for line in text.splitlines() if not line.startswith("/ruff.toml")]
    assert len(kept) == len(text.splitlines()) - 1
    copy = tmp_path / "CODEOWNERS"
    copy.write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert _unowned_guardrails(copy) == ["ruff.toml"]


def test_exempt_patterns_are_not_required_in_codeowners() -> None:
    assert ".git/hooks/**" in GUARDRAIL_PATTERNS
    assert ".git/hooks/**" not in _unowned_guardrails()

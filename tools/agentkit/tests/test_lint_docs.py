import textwrap
from pathlib import Path

import pytest

from sb_agentkit.lint_docs import defined_rule_ids, lint, read_frontmatter


def write(root: Path, rel: str, text: str) -> None:
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(text))


@pytest.fixture
def good(tmp_path: Path) -> Path:
    write(
        tmp_path,
        "AGENTS.md",
        "# Agents\nFollow A1 and T3. See [conv](docs/conventions/architecture.md).\n",
    )
    write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
    write(tmp_path, "docs/conventions/architecture.md", "# Arch\n### A1 — Layers\n")
    write(tmp_path, "docs/conventions/testing.md", "# Test\n### T3 — Fakes\n")
    write(
        tmp_path,
        ".claude/skills/tdd/SKILL.md",
        "---\nname: tdd\ndescription: TDD loop for T3.\n---\n# TDD\n",
    )
    write(
        tmp_path,
        ".claude/agents/explorer.md",
        "---\nname: explorer\ndescription: finds code\ntools: Read, Grep\n---\nBody\n",
    )
    write(
        tmp_path,
        ".claude/rules/tests.md",
        '---\npaths:\n  - "**/tests/**"\n---\nUse fakes (T3).\n',
    )
    return tmp_path


def test_clean_repo_has_no_problems(good: Path) -> None:
    assert lint(good) == []


def test_defined_rule_ids_come_from_headings(good: Path) -> None:
    assert defined_rule_ids(good) == {"A1", "T3"}


def test_read_frontmatter_returns_mapping_and_body_line() -> None:
    meta, body_line = read_frontmatter("---\nname: x\n---\nbody\n")
    assert meta == {"name": "x"}
    assert body_line == 4
    assert read_frontmatter("no frontmatter") == (None, 1)


def test_undefined_rule_id_reports_file_and_line(good: Path) -> None:
    write(good, ".claude/rules/extra.md", '---\npaths: ["x/**"]\n---\n\nSee C9 here.\n')
    assert lint(good) == [
        ".claude/rules/extra.md:5: cites rule C9, not defined in docs/conventions"
    ]


def test_dead_relative_link_is_reported(good: Path) -> None:
    write(good, "docs/agents/README.md", "Read [hooks](hooks.md) and [web](https://x.io).\n")
    assert lint(good) == ["docs/agents/README.md:1: link target hooks.md does not exist"]


def test_link_anchor_is_ignored(good: Path) -> None:
    write(good, "docs/agents/README.md", "[a](../conventions/architecture.md#a1--layers)\n")
    assert lint(good) == []


def test_agents_md_too_long(good: Path) -> None:
    write(good, "AGENTS.md", "x\n" * 101)
    assert "AGENTS.md:101: AGENTS.md has 101 lines (max 100)" in lint(good)


def test_claude_md_must_import_agents_md(good: Path) -> None:
    write(good, "CLAUDE.md", "# Claude\n")
    assert "CLAUDE.md:1: must contain the line @AGENTS.md" in lint(good)


def test_skill_name_must_match_directory(good: Path) -> None:
    write(good, ".claude/skills/tdd/SKILL.md", "---\nname: other\ndescription: d\n---\n")
    assert ".claude/skills/tdd/SKILL.md:1: frontmatter name 'other' must equal 'tdd'" in lint(good)


def test_skill_without_frontmatter(good: Path) -> None:
    write(good, ".claude/skills/spec/SKILL.md", "# Spec\n")
    assert ".claude/skills/spec/SKILL.md:1: missing YAML frontmatter" in lint(good)


def test_agent_requires_tools(good: Path) -> None:
    write(good, ".claude/agents/explorer.md", "---\nname: explorer\ndescription: d\n---\n")
    assert ".claude/agents/explorer.md:1: frontmatter needs 'tools'" in lint(good)


def test_rule_requires_paths(good: Path) -> None:
    write(good, ".claude/rules/tests.md", "---\ndescription: x\n---\n")
    assert ".claude/rules/tests.md:1: frontmatter needs a non-empty 'paths' list" in lint(good)


def test_vision_and_adr_docs_are_not_scanned(good: Path) -> None:
    write(good, "docs/vision/north-star.md", "[x](missing.md) C99\n")
    write(good, "docs/adr/0001-x.md", "[x](missing.md)\n")
    assert lint(good) == []


def test_citation_in_prose_without_code_still_reported(good: Path) -> None:
    write(good, ".claude/rules/extra.md", '---\npaths: ["x/**"]\n---\n\nSee C9 (undefined).\n')
    assert lint(good) == [
        ".claude/rules/extra.md:5: cites rule C9, not defined in docs/conventions"
    ]


def test_citation_in_inline_code_is_ignored(good: Path) -> None:
    write(good, ".claude/rules/extra.md", '---\npaths: ["x/**"]\n---\n\nUse `C9` in code.\n')
    assert lint(good) == []


def test_citation_in_fenced_block_is_ignored(good: Path) -> None:
    write(
        good,
        ".claude/rules/extra.md",
        '---\npaths: ["x/**"]\n---\n\n```\nC9\n```\n',
    )
    assert lint(good) == []


def test_citation_on_ignore_line_is_ignored(good: Path) -> None:
    write(
        good,
        ".claude/rules/extra.md",
        '---\npaths: ["x/**"]\n---\n\nSee C9 here. <!-- agent-lint: ignore -->\n',
    )
    assert lint(good) == []


def test_line_numbers_correct_after_excluded_fenced_block(good: Path) -> None:
    write(
        good,
        ".claude/rules/extra.md",
        '---\npaths: ["x/**"]\n---\n\n```\nignored C9\n```\n\nSee C8 here.\n',
    )
    assert lint(good) == [
        ".claude/rules/extra.md:9: cites rule C8, not defined in docs/conventions"
    ]


def test_root_absolute_link_resolves_against_repo_root(good: Path) -> None:
    write(good, "docs/agents/README.md", "[a](/AGENTS.md)\n")
    assert lint(good) == []


def test_invalid_yaml_frontmatter_is_reported(good: Path) -> None:
    write(good, ".claude/skills/tdd/SKILL.md", "---\nname: [unclosed\n---\n# TDD\n")
    problems = lint(good)
    assert len(problems) == 1
    assert problems[0].startswith(".claude/skills/tdd/SKILL.md:1: invalid YAML frontmatter:")


def test_rule_id_defined_twice_is_reported(good: Path) -> None:
    write(good, "docs/conventions/coding.md", "# Coding\n\n### A1 — Also layers\n")
    assert lint(good) == [
        "docs/conventions/coding.md:3: rule A1 is defined more than once "
        "(also docs/conventions/architecture.md:2)"
    ]


def test_citations_in_conventions_are_checked(good: Path) -> None:
    write(good, "docs/conventions/testing.md", "# Test\n### T3 — Fakes\nSee C9.\n")
    assert lint(good) == [
        "docs/conventions/testing.md:3: cites rule C9, not defined in docs/conventions"
    ]


def test_citations_in_architecture_docs_are_checked(good: Path) -> None:
    write(good, "docs/architecture/overview.md", "# Overview\n\nLayers follow A1 and A99.\n")
    assert lint(good) == [
        "docs/architecture/overview.md:3: cites rule A99, not defined in docs/conventions"
    ]


def test_command_needs_description(good: Path) -> None:
    write(good, ".claude/commands/review.md", "---\nargument-hint: focus\n---\nRun it.\n")
    write(good, ".claude/commands/spec.md", "Draft a spec.\n")
    assert lint(good) == [
        ".claude/commands/review.md:1: frontmatter needs a 'description' of 1-1024 chars",
        ".claude/commands/spec.md:1: missing YAML frontmatter",
    ]


def test_command_with_description_is_clean(good: Path) -> None:
    write(good, ".claude/commands/review.md", "---\ndescription: Run the gate\n---\nRun it.\n")
    assert lint(good) == []


@pytest.mark.parametrize(
    "rel",
    [
        "docs/superpowers/plans/2026-10-01-new.md",
        "docs/superpowers/specs/2026-10-01-new.md",
        "docs/agents/ledgers/2026-10-01-new.md",
        "docs/reviews/new.md",
        "docs/investigations/2026-10-01-x/rca-report.md",
    ],
)
def test_new_working_doc_is_reported(good: Path, rel: str) -> None:
    write(good, rel, "# Notes\n")
    assert lint(good) == [
        f"{rel}:1: working doc; keep it in .work/<slug>/ (gitignored) and run the harvest skill"
    ]


def test_work_dir_is_not_scanned(good: Path) -> None:
    write(good, ".work/feature/plan.md", "[x](missing.md) C99\n")
    assert lint(good) == []


@pytest.mark.parametrize("member", ["services/ledger", "libs/py/sb_db", "tools/graph", "apps/web"])
def test_member_notes_over_budget_are_reported(good: Path, member: str) -> None:
    write(good, f"{member}/CLAUDE.md", "x" * 10_001)
    assert lint(good) == [
        f"{member}/CLAUDE.md:1: 10001 chars (max 10000); move items into tests or code comments"
    ]


def test_member_notes_at_budget_are_clean(good: Path) -> None:
    write(good, "services/ledger/CLAUDE.md", "x" * 10_000)
    assert lint(good) == []

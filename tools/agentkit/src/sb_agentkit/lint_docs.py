"""Keep the agent context layer coherent: frontmatter, rule-ID citations, links, size budgets.

Agents follow what they read. A skill citing a rule that was renamed, or a link to a moved
file, silently degrades every future session, so these are CI failures (ADR-0006). Working docs
(specs, plans, ledgers, reviews, investigations) stay in gitignored .work/ and go through the
harvest skill, so a committed one is a failure too.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import cast

import yaml

__all__ = ["defined_rule_ids", "lint", "read_frontmatter"]

AGENTS_MAX_LINES = 100
DESCRIPTION_MAX = 1024
SKILL_PARTS = 4
AGENT_OR_RULE_PARTS = 3
RULE_HEADING = re.compile(r"^#{2,4}\s+([ACT]\d{1,2})\b")
RULE_CITATION = re.compile(r"\b([ACT]\d{1,2})\b")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE_MARKER = re.compile(r"^(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
IGNORE_MARKER = "<!-- agent-lint: ignore -->"
EXCLUDED_DOC_DIRS = ("docs/superpowers", "docs/vision", "docs/generated", "docs/adr")
MEMBER_NOTES_MAX_CHARS = 10_000
MEMBER_NOTES_GLOBS = (
    "services/*/CLAUDE.md",
    "libs/py/*/CLAUDE.md",
    "tools/*/CLAUDE.md",
    "apps/*/CLAUDE.md",
)
WORKING_DOC_DIRS = (
    "docs/superpowers",
    "docs/agents/ledgers",
    "docs/reviews",
    "docs/investigations",
)
CITATION_SCOPES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude",
    "docs/agents",
    "docs/conventions",
    "docs/architecture",
)


def read_frontmatter(text: str) -> tuple[dict[str, object] | None, int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, 1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            loaded: object = yaml.safe_load("\n".join(lines[1:index])) or {}
            meta = cast(dict[str, object], loaded) if isinstance(loaded, dict) else {}
            return meta, index + 2
    return None, 1


def _rule_definitions(root: Path) -> dict[str, list[tuple[PurePosixPath, int]]]:
    """Every rule-ID heading in docs/conventions, in file then line order."""
    definitions: dict[str, list[tuple[PurePosixPath, int]]] = {}
    conventions = root / "docs" / "conventions"
    for file in sorted(conventions.glob("*.md")) if conventions.is_dir() else []:
        rel = PurePosixPath(file.relative_to(root).as_posix())
        lines = file.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            match = RULE_HEADING.match(line)
            if match:
                definitions.setdefault(match.group(1), []).append((rel, number))
    return definitions


def defined_rule_ids(root: Path) -> set[str]:
    return set(_rule_definitions(root))


def _check_duplicate_rules(root: Path) -> Iterator[str]:
    for rule, places in _rule_definitions(root).items():
        (first_rel, first_line), *others = places
        for rel, line in others:
            yield (
                f"{rel}:{line}: rule {rule} is defined more than once "
                f"(also {first_rel}:{first_line})"
            )


def _scanned_files(root: Path) -> Iterator[PurePosixPath]:
    for name in ("AGENTS.md", "CLAUDE.md"):
        if (root / name).is_file():
            yield PurePosixPath(name)
    for base in (".claude", "docs"):
        directory = root / base
        for file in sorted(directory.rglob("*.md")) if directory.is_dir() else []:
            rel = PurePosixPath(file.relative_to(root).as_posix())
            if not any(rel.is_relative_to(excluded) for excluded in EXCLUDED_DOC_DIRS):
                yield rel


def _resolve_link(root: Path, rel: PurePosixPath, path: str) -> Path:
    if path.startswith("/"):
        return root / path.lstrip("/")
    return root / rel.parent / path


def _check_links(root: Path, rel: PurePosixPath, lines: list[str]) -> Iterator[str]:
    for number, line in enumerate(lines, start=1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not _resolve_link(root, rel, path).exists():
                yield f"{rel}:{number}: link target {path} does not exist"


def _citation_lines(lines: list[str]) -> Iterator[tuple[int, str]]:
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if FENCE_MARKER.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence or IGNORE_MARKER in line:
            continue
        yield number, INLINE_CODE.sub("", line)


def _check_citations(rel: PurePosixPath, lines: list[str], ids: set[str]) -> Iterator[str]:
    if not any(rel == PurePosixPath(s) or rel.is_relative_to(s) for s in CITATION_SCOPES):
        return
    for number, text in _citation_lines(lines):
        for rule in RULE_CITATION.findall(text):
            if rule not in ids:
                yield f"{rel}:{number}: cites rule {rule}, not defined in docs/conventions"


def _check_frontmatter(rel: PurePosixPath, text: str) -> Iterator[str]:
    parts = rel.parts
    is_skill = (
        len(parts) == SKILL_PARTS and parts[:2] == (".claude", "skills") and parts[3] == "SKILL.md"
    )
    is_agent = len(parts) == AGENT_OR_RULE_PARTS and parts[:2] == (".claude", "agents")
    is_rule = len(parts) == AGENT_OR_RULE_PARTS and parts[:2] == (".claude", "rules")
    is_command = len(parts) == AGENT_OR_RULE_PARTS and parts[:2] == (".claude", "commands")
    if not (is_skill or is_agent or is_rule or is_command):
        return
    try:
        meta, _ = read_frontmatter(text)
    except yaml.YAMLError as exc:
        reason = str(exc).splitlines()[0].strip()
        yield f"{rel}:1: invalid YAML frontmatter: {reason}"
        return
    if meta is None:
        yield f"{rel}:1: missing YAML frontmatter"
        return
    if is_command:
        yield from _check_description(rel, meta)
    elif is_skill:
        yield from _check_named(rel, meta, parts[2])
    elif is_agent:
        yield from _check_named(rel, meta, rel.stem)
        if not meta.get("tools"):
            yield f"{rel}:1: frontmatter needs 'tools'"
    else:
        paths = meta.get("paths")
        valid = False
        if isinstance(paths, list) and paths:
            items = cast(list[object], paths)
            valid = all(isinstance(p, str) for p in items)
        if not valid:
            yield f"{rel}:1: frontmatter needs a non-empty 'paths' list"


def _check_named(rel: PurePosixPath, meta: dict[str, object], expected: str) -> Iterator[str]:
    name = meta.get("name")
    if name != expected:
        yield f"{rel}:1: frontmatter name {name!r} must equal {expected!r}"
    yield from _check_description(rel, meta)


def _check_description(rel: PurePosixPath, meta: dict[str, object]) -> Iterator[str]:
    description = meta.get("description")
    if not isinstance(description, str) or not 0 < len(description) <= DESCRIPTION_MAX:
        yield f"{rel}:1: frontmatter needs a 'description' of 1-{DESCRIPTION_MAX} chars"


def _check_top_level(root: Path) -> Iterator[str]:
    agents = root / "AGENTS.md"
    if not agents.is_file():
        yield "AGENTS.md:1: missing"
    else:
        count = len(agents.read_text(encoding="utf-8").splitlines())
        if count > AGENTS_MAX_LINES:
            yield f"AGENTS.md:{count}: AGENTS.md has {count} lines (max {AGENTS_MAX_LINES})"
    claude = root / "CLAUDE.md"
    if not claude.is_file() or "@AGENTS.md" not in claude.read_text(encoding="utf-8").split():
        yield "CLAUDE.md:1: must contain the line @AGENTS.md"


def _check_working_docs(root: Path) -> Iterator[str]:
    for base in WORKING_DOC_DIRS:
        directory = root / base
        for file in sorted(directory.rglob("*.md")) if directory.is_dir() else []:
            rel = file.relative_to(root).as_posix()
            yield (
                f"{rel}:1: working doc; keep it in .work/<slug>/ (gitignored) "
                "and run the harvest skill"
            )


def _check_member_notes(root: Path) -> Iterator[str]:
    for pattern in MEMBER_NOTES_GLOBS:
        for file in sorted(root.glob(pattern)):
            size = len(file.read_text(encoding="utf-8"))
            if size > MEMBER_NOTES_MAX_CHARS:
                rel = file.relative_to(root).as_posix()
                yield (
                    f"{rel}:1: {size} chars (max {MEMBER_NOTES_MAX_CHARS}); "
                    "move items into tests or code comments"
                )


def lint(root: Path) -> list[str]:
    ids = defined_rule_ids(root)
    problems = [
        *_check_top_level(root),
        *_check_duplicate_rules(root),
        *_check_working_docs(root),
        *_check_member_notes(root),
    ]
    for rel in _scanned_files(root):
        text = (root / rel).read_text(encoding="utf-8")
        lines = text.splitlines()
        problems.extend(_check_frontmatter(rel, text))
        problems.extend(_check_links(root, rel, lines))
        problems.extend(_check_citations(rel, lines, ids))
    return sorted(problems)

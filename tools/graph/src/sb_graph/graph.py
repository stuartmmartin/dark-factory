"""The workspace dependency graph and its queries (closures, owners, validation)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sb_graph.imports import actual_internal_deps
from sb_graph.workspace import Member, discover_members


class GraphError(ValueError):
    """A graph query referenced an unknown member."""


@dataclass(frozen=True)
class Graph:
    members: tuple[Member, ...]

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((m.name, dep) for m in self.members for dep in m.declared))

    @property
    def test_edges(self) -> tuple[tuple[str, str], ...]:
        """Test-only edges ([dependency-groups]) not already runtime edges."""
        return tuple(
            sorted(
                (m.name, dep)
                for m in self.members
                for dep in m.test_declared
                if dep not in m.declared
            )
        )

    def member(self, name: str) -> Member:
        for member in self.members:
            if member.name == name:
                return member
        known = ", ".join(m.name for m in self.members)
        raise GraphError(f"unknown member {name!r}; known members: {known}")

    def dependents(self, name: str) -> tuple[str, ...]:
        """Members whose code or tests depend on NAME (runtime + test edges)."""
        return tuple(
            sorted(m.name for m in self.members if name in m.declared or name in m.test_declared)
        )

    def deps_closure(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(self._reachable(name, lambda n: self.member(n).declared) - {name}))

    def dependents_closure(self, name: str) -> tuple[str, ...]:
        self.member(name)
        return tuple(sorted(self._reachable(name, self.dependents) - {name}))

    def in_cycle(self, name: str) -> bool:
        return name in self._reachable(name, lambda n: self.member(n).declared)

    def owner_of(self, path: PurePosixPath) -> Member | None:
        owners = [m for m in self.members if path.is_relative_to(m.path)]
        return max(owners, key=lambda m: len(m.path.parts), default=None)

    def _reachable(self, start: str, step: Callable[[str], Iterable[str]]) -> set[str]:
        seen: set[str] = set()
        frontier = list(step(start))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(step(current))
        return seen


def load_graph(root: Path) -> Graph:
    return Graph(discover_members(root))


def validate(root: Path, graph: Graph) -> list[str]:
    errors: list[str] = []
    for member in graph.members:
        actual = set(actual_internal_deps(root, member, graph.members))
        declared = set(member.declared)
        errors.extend(
            f"{member.name}: imports {dep} but does not declare it in "
            f"{member.path}/pyproject.toml [project].dependencies"
            for dep in sorted(actual - declared)
        )
        errors.extend(
            f"{member.name}: declares {dep} but never imports it from src/"
            for dep in sorted(declared - actual)
        )
        if graph.in_cycle(member.name):
            errors.append(f"{member.name}: dependency cycle through {member.name}")
    return errors

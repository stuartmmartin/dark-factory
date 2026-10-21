import ast
import json
from pathlib import Path

import pytest

from sb_graph.graph import load_graph
from sb_graph.render import (
    GENERATED_MARKER,
    generated_files,
    public_symbols,
    render_json,
    render_mermaid,
)


@pytest.fixture
def repo(workspace: Path, add_member) -> Path:
    add_member(
        "libs/py/sb_kernel",
        "sb-kernel",
        files={
            "src/sb_kernel/__init__.py": '"""Pure core types."""\n',
            "src/sb_kernel/money.py": (
                '"""Money value object.\n\nMore detail."""\n'
                "__all__ = ['Money']\n"
                "class Money: ...\n"
                "class Hidden: ...\n"
                "def _private(): ...\n"
            ),
        },
    )
    add_member(
        "services/ledger",
        "ledger",
        deps=["sb-kernel"],
        files={"src/ledger/__init__.py": "import sb_kernel\n"},
        extra_toml='[dependency-groups]\ntest = ["sb-testkit"]\n',
    )
    add_member("libs/py/sb_testkit", "sb-testkit", files={"src/sb_testkit/__init__.py": ""})
    return workspace


def test_json_is_sorted_and_versioned(repo: Path) -> None:
    data = json.loads(render_json(load_graph(repo)))
    assert data["schema_version"] == 2
    assert data["_generated"] == GENERATED_MARKER
    assert [m["name"] for m in data["members"]] == ["ledger", "sb-kernel", "sb-testkit"]
    assert data["edges"] == [["ledger", "sb-kernel"]]
    assert data["test_edges"] == [["ledger", "sb-testkit"]]
    assert data["members"][0]["test_depends_on"] == ["sb-testkit"]


def test_mermaid_has_nodes_and_edges(repo: Path) -> None:
    text = render_mermaid(load_graph(repo))
    assert "flowchart LR" in text
    assert "ledger --> sb_kernel" in text
    assert "ledger -.-> sb_testkit" in text
    assert "ledger --> sb_testkit" not in text


def test_module_index_lists_docstring_summary_and_public_api(repo: Path) -> None:
    index = generated_files(repo, load_graph(repo))
    text = next(v for k, v in index.items() if k.name == "module-index.md")
    assert "- `sb_kernel.money` — Money value object." in text
    assert "  - `class Money`" in text
    assert "Hidden" not in text
    assert "_private" not in text
    assert "- `sb_kernel` — Pure core types." in text
    assert "Test depends on: sb-testkit" in text


def test_public_symbols_truncates_long_signatures() -> None:
    args = ", ".join(f"argument_number_{i}: int" for i in range(10))
    tree = ast.parse(f"def f({args}) -> None: ...\n")
    [signature] = public_symbols(tree)
    assert len(signature) == 120
    assert signature.endswith("...")


def test_output_is_deterministic_and_has_no_absolute_paths(repo: Path) -> None:
    first = generated_files(repo, load_graph(repo))
    second = generated_files(repo, load_graph(repo))
    assert first == second
    for content in first.values():
        assert str(repo) not in content
        assert content.endswith("\n")

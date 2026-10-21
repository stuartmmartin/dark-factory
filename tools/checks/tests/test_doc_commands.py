from pathlib import Path

import pytest

from sb_checks import cli, doc_commands

DOC = """# Title

```sh
brew install docker
```

```sh env-setup
make bootstrap
```

Text.

```sh env-setup
cp -n .env.example .env || true
make doctor
```
"""


def test_extract_returns_only_env_setup_blocks_in_order() -> None:
    assert doc_commands.extract(DOC) == [
        "make bootstrap\n",
        "cp -n .env.example .env || true\nmake doctor\n",
    ]


def test_extract_honours_the_tag() -> None:
    assert doc_commands.extract("```sh other\nx\n```\n", tag="other") == ["x\n"]
    assert doc_commands.extract("```sh other\nx\n```\n") == []


def test_extract_rejects_an_unterminated_block() -> None:
    with pytest.raises(doc_commands.DocError, match="unterminated"):
        doc_commands.extract("```sh env-setup\nnever closed\n")


@pytest.mark.parametrize("fence", ["```sh env-setup extra", "```bash env-setup", "```env-setup"])
def test_extract_rejects_a_fence_variant_that_would_be_ignored(fence: str) -> None:
    with pytest.raises(doc_commands.DocError, match="ignored"):
        doc_commands.extract(f"{fence}\nmake up\n```\n")


def test_cli_exits_one_on_a_bad_fence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("```sh env-setup\nnever closed\n")
    assert cli.main(["doc-commands", str(doc)]) == 1
    assert "unterminated" in capsys.readouterr().err


def test_run_times_out_a_slow_block(tmp_path: Path) -> None:
    with pytest.raises(doc_commands.BlockTimeoutError, match="block 2 timed out"):
        doc_commands.run(["true\n", "sleep 5\n"], tmp_path, timeout=0.2)


def test_cli_reports_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(doc_commands, "BLOCK_TIMEOUT_SECONDS", 0.2)
    doc = tmp_path / "doc.md"
    doc.write_text("```sh env-setup\nsleep 5\n```\n")
    assert cli.main(["doc-commands", str(doc), "--run", "--root", str(tmp_path)]) == 1
    assert "timed out" in capsys.readouterr().err


def test_real_environment_setup_doc_has_the_ten_blocks_in_order() -> None:
    doc = Path(__file__).resolve().parents[3] / "docs" / "environment_setup.md"
    firsts = [b.splitlines()[0] for b in doc_commands.extract(doc.read_text())]
    assert firsts == [
        "make bootstrap",
        "cp -n .env.example .env || true",
        "make doctor",
        "make up infra",
        "make up ledger",
        "curl -fsS --retry 10 --retry-delay 3 --retry-all-errors "
        "http://localhost:${SB_LEDGER_API_PORT:-8001}/health/ready",
        "make seed SVC=ledger",
        'uv run ledger-cli open "Owner equity" --idempotency-key setup-owner-equity',
        "make test-unit",
        "make down",
    ]


def test_cli_prints_the_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(DOC)
    assert cli.main(["doc-commands", str(doc)]) == 0
    out = capsys.readouterr().out
    assert "make bootstrap" in out
    assert "brew install docker" not in out


def test_run_stops_at_the_first_failing_block_and_reports_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "never"
    doc = tmp_path / "doc.md"
    doc.write_text(
        f"```sh env-setup\ntrue\n```\n\n```sh env-setup\nfalse\n```\n\n"
        f"```sh env-setup\ntouch {marker}\n```\n"
    )
    assert cli.main(["doc-commands", str(doc), "--run", "--root", str(tmp_path)]) == 1
    assert "block 2 of 3 failed" in capsys.readouterr().err
    assert not marker.exists()


def test_run_uses_pipefail_and_errexit_from_the_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("```sh env-setup\nfalse | true\n```\n\n```sh env-setup\nfalse\ntrue\n```\n")
    assert cli.main(["doc-commands", str(doc), "--run", "--root", str(tmp_path)]) == 1
    assert "block 1 of 2 failed" in capsys.readouterr().err


def test_run_succeeds_in_the_repo_root(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("```sh env-setup\ntest -f marker\n```\n")
    (tmp_path / "marker").write_text("")
    assert cli.main(["doc-commands", str(doc), "--run", "--root", str(tmp_path)]) == 0


def test_a_doc_without_blocks_is_an_error(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("no blocks\n")
    assert cli.main(["doc-commands", str(doc)]) == 1

import json
from pathlib import Path

import pytest

from sb_agentkit.hookio import HookInput
from sb_agentkit.pre_bash import check_pre_bash, split_segments


def _bash(command: str) -> HookInput:
    raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    parsed = HookInput.parse(raw, default_cwd=Path("/repo"))
    assert parsed is not None
    return parsed


def test_split_segments_handles_operators_and_quotes() -> None:
    assert split_segments("cd x && pytest -k 'a b' | tee o; echo done") == [
        ["cd", "x"],
        ["pytest", "-k", "a b"],
        ["tee", "o"],
        ["echo", "done"],
    ]


@pytest.mark.parametrize(
    "command",
    [
        "pytest tools/checks",
        "uv run pytest -k foo",
        "python -m pytest -x",
        "alembic upgrade head",
        "uv run alembic revision -m x",
        "docker compose up -d",
        "docker-compose logs",
        "docker compose exec postgres psql -U sb_admin -d ledger",
        "psql postgresql://localhost:5432/ledger -c 'select 1'",
    ],
)
def test_raw_test_db_and_compose_tools_are_allowed(command: str) -> None:
    assert not check_pre_bash(_bash(command)).block


@pytest.mark.parametrize(
    "command",
    ["cat .env", "less services/ledger/.env", "head -5 .env.local", "grep KEY .env"],
)
def test_blocks_reading_secret_files(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin feat",
        "git push -f",
        "git push --force-with-lease",
        "git commit --no-verify -m x",
    ],
)
def test_blocks_history_rewrites_and_hook_bypass(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


@pytest.mark.parametrize(
    "command",
    [
        "make test PKG=tools/checks ARGS='-k pytest'",
        "echo pytest",
        "git commit -m 'run pytest via make'",
        "git push origin main",
        "git push origin HEAD:main",
        "cat .env.example",
        "rg alembic docs/",
        "ls",
        "",
    ],
)
def test_allows_ordinary_commands(command: str) -> None:
    assert not check_pre_bash(_bash(command)).block


def test_unparseable_quotes_fall_back_to_allow() -> None:
    assert not check_pre_bash(_bash("echo 'unterminated")).block


@pytest.mark.parametrize(
    "command",
    ["cat .ENV", "less services/ledger/.ENV", "head -5 .ENV.LOCAL", "grep KEY .Env"],
)
def test_blocks_reading_secret_files_case_insensitively(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


def test_git_commit_dash_n_bypasses_no_verify() -> None:
    assert check_pre_bash(_bash("git commit -n -m x")).block


@pytest.mark.parametrize(
    "command",
    [
        "git --no-pager commit --no-verify -m x",
        "git -c core.editor=vi push --force",
    ],
)
def test_subcommand_is_found_past_global_options(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


def test_split_segments_treats_bare_ampersand_as_separator() -> None:
    assert split_segments("pytest & echo done") == [["pytest"], ["echo", "done"]]


def test_bare_ampersand_backgrounding_does_not_hide_a_force_push() -> None:
    assert check_pre_bash(_bash("true & git push --force")).block


@pytest.mark.parametrize(
    "command",
    [
        "env FOO=1 git push --force",
        "command git push --force",
        "exec git push --force",
        "nohup git push --force",
        "time git push --force",
        "/usr/bin/git push --force",
        "./bin/git push -f",
    ],
)
def test_wrapped_and_pathed_git_is_still_checked(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


class TestDocumentedBlindSpots:
    """Known gaps: sb-agentkit inspects argv only, not shell substitution or expansion."""

    def test_backtick_substitution_is_not_caught(self) -> None:
        assert not check_pre_bash(_bash("echo `git push --force`")).block

    def test_eval_is_not_caught(self) -> None:
        assert not check_pre_bash(_bash("eval 'git push --force'")).block


@pytest.mark.parametrize(
    "command",
    [
        "git --exec-path /x commit --no-verify",
        "git --namespace foo push --force",
    ],
)
def test_subcommand_scan_survives_unknown_value_options(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


@pytest.mark.parametrize(
    "command",
    [
        "git log -n 5",
        "git -C . log",
        "git stash push -m x",
        "docker image ls",
    ],
)
def test_subcommand_scan_does_not_false_positive(command: str) -> None:
    assert not check_pre_bash(_bash(command)).block


@pytest.mark.parametrize("command", ["command -p git push -f", "time -p git push -f"])
def test_wrapper_own_options_are_stripped(command: str) -> None:
    assert check_pre_bash(_bash(command)).block


class TestQuotedOperators:
    """I3: quoted `;`, `|`, `&&` are argument text, not command separators."""

    @pytest.mark.parametrize(
        "command",
        [
            'echo "a; cat .env"',
            "echo 'x | git push --force'",
            'git commit -m "fix: a && b; c | d"',
            'rg "foo|bar;baz" src',
            "rg 'push --force && cat .env' docs/",
        ],
    )
    def test_quoted_operators_are_not_split(self, command: str) -> None:
        assert not check_pre_bash(_bash(command)).block

    @pytest.mark.parametrize(
        "command",
        [
            'git commit --no-verify -m "a; b"',
            'git commit -m "a | b" --no-verify',
            'echo "x;y" && git push --force',
            "echo 'a|b' | cat .env",
            "ls\ngit push --force",
            "(git push --force)",
            "echo $(cat .env)",
        ],
    )
    def test_real_operators_still_split(self, command: str) -> None:
        assert check_pre_bash(_bash(command)).block

    def test_split_segments_keeps_quoted_operator_text(self) -> None:
        assert split_segments('git commit -m "a; b" && ls') == [
            ["git", "commit", "-m", "a; b"],
            ["ls"],
        ]

    def test_hash_inside_a_word_does_not_hide_the_rest(self) -> None:
        assert check_pre_bash(_bash("echo a#b; git push --force")).block


class TestUnparseableFallback:
    """I3: an unterminated quote falls back to a conservative scan of the raw string."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit --no-verify -m 'unterminated",
            "git push --force origin 'x",
            "git push -f 'x",
            "cat .env 'x",
            'cat services/a/.env.local "x',
        ],
    )
    def test_high_risk_patterns_are_blocked(self, command: str) -> None:
        assert check_pre_bash(_bash(command)).block

    @pytest.mark.parametrize("command", ["echo 'unterminated", "cat .env.example 'x"])
    def test_other_unparseable_commands_are_allowed(self, command: str) -> None:
        assert not check_pre_bash(_bash(command)).block


class TestWrappersAndShells:
    """M1: wrappers and nested shells."""

    @pytest.mark.parametrize(
        "command",
        [
            "uv run --package sb-graph git push --force",
            "uv run --with hypothesis cat .env",
            "uv run -- git push -f",
            "uv run --frozen --package x -- git push -f",
            "uvx --from x cat .env",
            "timeout 60 git push --force",
            "timeout -s KILL 60 git push --force",
            "nice git push --force",
            "nice -n 10 git push --force",
            "sudo git push --force",
            "sudo -u bob git push --force",
            "xargs git push --force",
            "xargs -n 1 cat .env",
            "find . -name x | xargs -I {} git push --force {}",
            'bash -c "git push --force"',
            "sh -c 'cd x && git commit --no-verify -m x'",
            "bash -lc 'cat .env'",
            'sudo bash -c "timeout 5 uv run git push --force"',
        ],
    )
    def test_wrapped_blocked_commands_are_still_blocked(self, command: str) -> None:
        assert check_pre_bash(_bash(command)).block, command

    @pytest.mark.parametrize(
        "command",
        [
            'bash -c "echo git push --force"',
            "python -c 'print(1)'",
            "timeout 5 ls",
            "xargs echo",
            "uv run --package x sb-graph check",
        ],
    )
    def test_wrapped_ordinary_commands_are_allowed(self, command: str) -> None:
        assert not check_pre_bash(_bash(command)).block


class TestGitGaps:
    """M1: hooks path overrides, bundled short flags, `+ref` force pushes."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -c core.hooksPath=/dev/null commit -m x",
            "git -c CORE.HOOKSPATH=x push",
            "git config core.hooksPath /tmp/none",
            "git commit -nm x",
            "git commit -m x -n",
            "git commit -S -n -m x",
            "git commit -u -n -m x",
            "git commit -a -S -n -m x",
            "git --config-env=core.hooksPath=VAR commit -m x",
            "git --config-env=CORE.HOOKSPATH=VAR commit -m x",
            "git config -f .git/config core.hooksPath /tmp/x",
            "git config --file .git/config core.hooksPath /tmp/x",
            "git config --type path core.hooksPath /tmp/x",
            "git config --global core.hooksPath /tmp/x",
            "git commit --message x -n",
            "git -c core.hooksPath=/dev/null commit",
            "git config --local CORE.HOOKSPATH /tmp/none",
            "git commit -an -m x",
            "git commit -anm x",
            "git push origin +main",
            "git push origin +HEAD:feat",
            "git push -uf origin feat",
        ],
    )
    def test_blocked(self, command: str) -> None:
        assert check_pre_bash(_bash(command)).block, command

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -am x",
            "git commit -m 'no -n here'",
            "git commit -mnice",
            "git push -u origin feat",
            "git push origin feat",
            "git log -n 3",
            "git commit -m 'document core.hooksPath change'",
            "git grep core.hooksPath",
            "git commit -m '-n is a flag'",
            "git commit --message '-n is a flag'",
            "git commit -am '-n is a flag'",
            "git commit --author '-n <a@b.c>' -m x",
            "git commit -S -m x",
            "git commit -t '-n tmpl' -m x",
            "git commit -F '-n.txt'",
            "git commit --reuse-message '-n' ",
            "git config user.name x",
            "git config --file f.cfg user.name x",
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert not check_pre_bash(_bash(command)).block, command


@pytest.mark.parametrize(
    "command",
    [
        "source .env",
        ". .env",
        "cp .env /tmp/x",
        "base64 .env",
        "xxd .env.local",
        "od -c .env",
        "python3 -c 'print(open(\".env\").read())' .env",
        ".venv/bin/python read.py services/x/.env",
        "cat < .env",
    ],
)
def test_more_secret_readers_are_blocked(command: str) -> None:
    decision = check_pre_bash(_bash(command))
    assert decision.block
    assert ".env.example" in decision.message


@pytest.mark.parametrize("command", ["source .venv/bin/activate", "cp .env.example /tmp/keys.txt"])
def test_ordinary_source_and_cp_are_allowed(command: str) -> None:
    assert not check_pre_bash(_bash(command)).block

import io
import json
from pathlib import Path

from sb_agentkit.hookio import Decision, HookInput, emit


def test_parse_reads_known_fields(tmp_path: Path) -> None:
    raw = (
        '{"hook_event_name": "PreToolUse", "tool_name": "Bash", '
        '"tool_input": {"command": "ls"}, "cwd": "/x", "stop_hook_active": true}'
    )
    inp = HookInput.parse(raw, default_cwd=tmp_path)
    assert inp is not None
    assert (inp.event, inp.tool_name, inp.tool_input, inp.cwd, inp.stop_hook_active) == (
        "PreToolUse",
        "Bash",
        {"command": "ls"},
        Path("/x"),
        True,
    )


def test_parse_tolerates_missing_keys(tmp_path: Path) -> None:
    inp = HookInput.parse("{}", default_cwd=tmp_path)
    assert inp is not None
    assert (inp.event, inp.tool_name, inp.tool_input, inp.cwd, inp.stop_hook_active) == (
        "",
        "",
        {},
        tmp_path,
        False,
    )


def test_parse_returns_none_for_garbage(tmp_path: Path) -> None:
    assert HookInput.parse("not json", default_cwd=tmp_path) is None
    assert HookInput.parse("[1, 2]", default_cwd=tmp_path) is None
    assert HookInput.parse("", default_cwd=tmp_path) is None


def test_emit_allow_is_zero_and_silent() -> None:
    err = io.StringIO()
    assert emit(Decision.allow(), err) == 0
    assert err.getvalue() == ""


def test_emit_deny_is_two_with_message() -> None:
    err = io.StringIO()
    assert emit(Decision.deny("nope"), err) == 2
    assert err.getvalue() == "nope\n"


def test_emit_informational_is_zero_with_context_on_stdout() -> None:
    err, out = io.StringIO(), io.StringIO()
    assert emit(Decision.inform("fyi"), err, out, event="PostToolUse") == 0
    assert err.getvalue() == ""
    assert json.loads(out.getvalue()) == {
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "fyi"}
    }


def test_session_id_is_parsed_and_defaults_to_empty() -> None:
    with_id = HookInput.parse('{"session_id": "abc"}', default_cwd=Path("/r"))
    without = HookInput.parse("{}", default_cwd=Path("/r"))
    odd = HookInput.parse('{"session_id": 5}', default_cwd=Path("/r"))
    assert with_id is not None
    assert without is not None
    assert odd is not None
    assert (with_id.session_id, without.session_id, odd.session_id) == ("abc", "", "")

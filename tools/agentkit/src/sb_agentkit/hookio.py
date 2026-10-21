"""Claude Code hook protocol: parse the stdin JSON payload, turn a Decision into an exit code."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO, cast

BLOCK_EXIT_CODE = 2
FILE_PATH_KEYS = ("file_path", "notebook_path", "path")


@dataclass(frozen=True)
class HookInput:
    event: str
    tool_name: str
    tool_input: dict[str, object] = field(default_factory=dict[str, object])
    cwd: Path = Path()
    stop_hook_active: bool = False
    session_id: str = ""

    @classmethod
    def parse(cls, raw: str, default_cwd: Path) -> HookInput | None:
        try:
            data: object = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        payload = cast(dict[str, object], data)
        tool_input = payload.get("tool_input")
        cwd = payload.get("cwd")
        session_id = payload.get("session_id")
        return cls(
            event=str(payload.get("hook_event_name", "")),
            tool_name=str(payload.get("tool_name", "")),
            tool_input=cast(dict[str, object], tool_input) if isinstance(tool_input, dict) else {},
            cwd=Path(cwd) if isinstance(cwd, str) and cwd else default_cwd,
            stop_hook_active=payload.get("stop_hook_active") is True,
            session_id=session_id if isinstance(session_id, str) else "",
        )

    def text(self, key: str) -> str:
        value = self.tool_input.get(key)
        return value if isinstance(value, str) else ""

    def target(self) -> str:
        """The file the tool acts on: `file_path`, `notebook_path`, or Grep/Glob `path`."""
        return next((self.text(key) for key in FILE_PATH_KEYS if self.text(key)), "")


@dataclass(frozen=True)
class Decision:
    """`block` with a message: exit 2, message to the agent on stderr. Not blocking with a
    message (`inform`): exit 0, message handed to the agent as additional context."""

    block: bool
    message: str = ""

    @classmethod
    def allow(cls) -> Decision:
        return cls(block=False)

    @classmethod
    def deny(cls, message: str) -> Decision:
        return cls(block=True, message=message)

    @classmethod
    def inform(cls, message: str) -> Decision:
        return cls(block=False, message=message)


def emit(decision: Decision, stderr: TextIO, stdout: TextIO | None = None, event: str = "") -> int:
    if not decision.block:
        if decision.message and stdout is not None:
            if event == "Stop":
                # Stop warnings belong to the user, not additional model context that can
                # trigger another completion attempt. Do not set decision=block on escalation.
                stdout.write(json.dumps({"systemMessage": decision.message}) + "\n")
            else:
                context = {"hookEventName": event, "additionalContext": decision.message}
                stdout.write(json.dumps({"hookSpecificOutput": context}) + "\n")
        return 0
    stderr.write(decision.message.rstrip("\n") + "\n")
    return BLOCK_EXIT_CODE

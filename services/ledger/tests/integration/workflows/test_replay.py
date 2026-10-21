"""Replay the committed AccountCountSnapshot history (D16, A12).

A nondeterministic change to the workflow fails here before deploy. The replayer uses the same
data converter and sandbox passthrough as `sb_workflows.worker.build_worker`. Regenerate the
history with `RECORD_HISTORY=1` on `test_account_count_snapshot.py` only when the workflow's
behaviour changes on purpose.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from ledger.interface.workflows.account_count_snapshot import AccountCountSnapshot
from sb_workflows.worker import PASSTHROUGH_MODULES

HISTORY = Path(__file__).parent / "histories" / "account_count_snapshot.json"


async def test_the_committed_history_replays() -> None:
    replayer = Replayer(
        workflows=[AccountCountSnapshot],
        data_converter=pydantic_data_converter,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(*PASSTHROUGH_MODULES)
        ),
    )
    history = WorkflowHistory.from_json("account-count-snapshot", HISTORY.read_text())
    result = await replayer.replay_workflow(history)
    assert result.replay_failure is None


def _identities(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "identity":
                yield str(v)
            else:
                yield from _identities(v)
    elif isinstance(node, list):
        for v in node:
            yield from _identities(v)


def test_the_committed_history_names_no_machine() -> None:
    """Worker identities ("<pid>@<hostname>") are scrubbed when the history is recorded."""
    identities = list(_identities(json.loads(HISTORY.read_text())))
    assert identities
    assert all("@" not in value for value in identities)

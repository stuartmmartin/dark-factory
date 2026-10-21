"""Structural invariants of .github/workflows/claude-review.yml that the gate's safety rests on."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "claude-review.yml"

Mapping = dict[str, object]


@pytest.fixture(scope="module")
def workflow() -> Mapping:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return cast(Mapping, loaded)


def _jobs(workflow: Mapping) -> dict[str, Mapping]:
    return cast(dict[str, Mapping], workflow["jobs"])


def _steps(job: Mapping) -> list[Mapping]:
    return cast(list[Mapping], job["steps"])


def test_label_events_do_not_trigger_the_gate(workflow: Mapping) -> None:
    """C1: any `labeled` event would re-run the gate and cancel the real review."""
    raw = cast(dict[object, object], workflow)
    triggers = cast(Mapping, raw.get("on", raw.get(True)))  # YAML 1.1 loads `on:` as True
    types = cast(list[str], cast(Mapping, triggers["pull_request"])["types"])
    assert "labeled" not in types
    assert set(types) == {"opened", "synchronize", "reopened", "ready_for_review"}


def test_strip_override_runs_first_on_every_event(workflow: Mapping) -> None:
    """C2: no `needs` (a failed preflight can't skip it) and no event filter."""
    job = _jobs(workflow)["strip-override"]
    assert "needs" not in job
    assert "if" not in job


def test_triage_requires_preflight_and_strip_override_to_succeed(workflow: Mapping) -> None:
    job = _jobs(workflow)["triage"]
    assert job["needs"] == ["preflight", "strip-override"]
    assert "if" not in job  # default success(): no always() escape hatch


def test_review_checkout_does_not_persist_credentials(workflow: Mapping) -> None:
    checkout = next(
        s
        for s in _steps(_jobs(workflow)["review"])
        if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert cast(Mapping, checkout["with"])["persist-credentials"] is False


def test_stale_review_result_is_removed_before_the_reviewer_runs(workflow: Mapping) -> None:
    steps = _steps(_jobs(workflow)["review"])
    action = next(
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("anthropics/claude-code-action@")
    )
    removals = [i for i, s in enumerate(steps) if "rm -f review-result.json" in str(s.get("run"))]
    assert removals
    assert removals[0] < action


def test_cache_key_covers_reviewer_agents_and_the_workflow(workflow: Mapping) -> None:
    key_step = next(s for s in _steps(_jobs(workflow)["review"]) if s.get("id") == "key")
    script = str(key_step["run"])
    for source in (
        ".claude/skills",
        ".claude/agents",
        "docs/conventions",
        "claude-review.yml",
        "tools/agentkit/src",
        "git rev-parse HEAD",
    ):
        assert source in script


def test_every_focus_enforces_the_validated_verdict(workflow: Mapping) -> None:
    steps = _steps(_jobs(workflow)["review"])
    verdict = next(s for s in steps if s.get("id") == "verdict")
    script = str(verdict["run"])
    assert "python3 tools/agentkit/src/sb_agentkit/review_result.py" in script
    assert '--focus "$REVIEWER"' in script
    assert '--commit "$(git rev-parse HEAD)"' in script
    gate = next(s for s in steps if "check-override.sh" in str(s.get("run")))
    assert "matrix.blocking" not in str(gate["if"])
    assert "steps.verdict.outputs.verdict != 'PASS'" in str(gate["if"])


def test_review_job_uses_stdlib_only_validator_and_supplies_commit(workflow: Mapping) -> None:
    steps = _steps(_jobs(workflow)["review"])
    assert not any("uv sync" in str(s.get("run")) for s in steps)
    assert not any("mise-action" in str(s.get("uses")) for s in steps)
    action = next(s for s in steps if str(s.get("uses", "")).startswith("anthropics/"))
    prompt = str(cast(Mapping, action["with"])["prompt"])
    assert "steps.key.outputs.commit" in prompt


def test_draft_prs_spend_no_review_tokens(workflow: Mapping) -> None:
    """Review runs once a PR is ready to merge (ready_for_review and later pushes), not on every
    push to a draft. Triage and review need preflight, so skipping it skips them."""
    jobs = _jobs(workflow)
    assert jobs["preflight"]["if"] == "${{ !github.event.pull_request.draft }}"
    assert "preflight" in cast(list[str], jobs["triage"]["needs"])

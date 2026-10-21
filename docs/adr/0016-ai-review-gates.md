# ADR-0016: AI review gates in CI; AI PRs are drafts

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Most code in this repo is written by AI agents, and "humans approve, machines prepare" is its
governing principle (spec §7.6). A human reviewer reading every line an agent writes doesn't
scale, but skipping automated review of
security- and architecture-sensitive changes trades reviewer time for real risk (auth bypasses,
layer/boundary violations that slip past a distracted reviewer). At the same time, AI review has a
known failure mode — false positives that get clicked through, or trusted uncritically — that the
spec's own risk table calls out explicitly (spec §12).

## Decision
`claude-review.yml` runs three review jobs on every PR via `anthropics/claude-code-action` at a
pinned SHA, after a preflight (`make lint` must pass before any API spend) and path-based
triage: **security** and **architecture** review are **blocking**; **engineering** review is
**advisory only**. Guardrail files (the list the agent hooks enforce) always get both blocking
reviewers. Every finding must be evidence-bound (a path in the diff plus a quoted hunk) or
it is dropped, and there is a documented `Disputed: [reason]` path plus a results cache keyed on
`(skill-version-hash, diff-hash)` to avoid re-litigating unchanged findings. A blocking finding can
be overridden only via an `override:ai-review` label applied by a user whose repository role is
admin or maintain (the owners), verified through the GitHub issue events API, not by anyone
editing the label. The workflow does not trigger on `labeled` events: the owner applies the label
and then re-runs the failed jobs, and the check reads the label's state at that moment. An
override applies only to the run it was granted on: a `strip-override` job with no dependencies
clears the label first on every triggering event (push, reopen, ready-for-review), so neither a
failed preflight nor a cancelled run can carry it over to a new commit.

The gate relies on branch protection: `ai-review-ok` and `ci-ok` are required checks, "Require
review from Code Owners" is on, and stale approvals are dismissed on new commits. The AI gate is
not a boundary against a PR that edits the gate itself (the workflow, the override script, the
reviewer skill); CODEOWNERS is, because those files are human-owned guardrails. Separately,
**every** AI-authored PR is opened with `gh pr create --draft` (spec §7.6), so a PR from an agent
is visibly not ready for merge until a human (or the review gates plus a human) has looked at it.

## Consequences
Security and architecture violations are caught before a human review even starts, for the
marginal cost of the blocking jobs' API spend and latency on every PR; engineering-quality
feedback is available without being able to block a merge on a stylistic disagreement with the
model. The known cost is the false-positive risk itself — mitigated, not eliminated, by evidence
binding, the dispute path, and (per the decision below) tracking the false-positive rate over
time; a reviewer who habitually clicks through findings without reading them defeats the gate
regardless of how good the evidence binding is.

## Revisit when
The false-positive rate, tracked quarterly (spec §12), is high enough that blocking jobs are
routinely overridden rather than acted on — at which point the fix is tightening the skills or the
evidence-binding bar, not removing the blocking gate.

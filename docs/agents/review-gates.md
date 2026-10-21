# Review gates

## Local: `/review`
Run once per branch, when it is ready to go into `main`, not per commit. The `code-review` skill dispatches the read-only `code-reviewer`. Every finding must cite a
path in the diff and quote the diff line, or it's dropped. The verdict is PASS, FAIL or BLOCKED;
PASS requires no blocking findings (advisories may be listed). A FAIL means fixing every blocking finding and its siblings,
then re-running. Findings the agent believes are false positives are listed as `Disputed:` for
a human to judge.

## CI: `.github/workflows/claude-review.yml`
Runs on `opened`, `synchronize`, `reopened` and `ready_for_review`, but skips draft PRs (preflight
is gated on `!draft`, and triage and review need it), so pushes to a draft spend no review tokens;
`ai-review-ok` treats the skipped jobs as passed. It deliberately does not run
on `labeled`: any label event would start a new run and, through `cancel-in-progress`, cancel
the real review.

1. **Strip-override** runs first on every triggering event, with no `needs`: it removes the
   `override:ai-review` label before anything else. An override is bound to the run it was
   granted on, so a new push, a reopen or a ready-for-review always clears it, even when
   preflight fails or an earlier run was cancelled.
2. **Preflight** (no API spend): `make lint` must pass first. It's deliberately minimal — full
   `make check` (typecheck, contracts, graph-check, tests) already runs in `ci.yml`, in parallel
   with this workflow, and gitleaks runs there too; this gate only needs enough of a sanity check
   to avoid spending API tokens reviewing code that doesn't even lint.
3. **Triage** (`sb-agentkit review-triage`, after both jobs above succeed) picks the reviewers
   from the changed paths:
   - `architecture` for any change to Python under `libs/`, `services/` or `tools/`, or to
     boundary config;
   - `security` for every service runtime change, platform HTTP/DB/admin/messaging/workflow/
     kernel/observability change, contracts, migrations, Docker, deploy or dependency changes;
   - `security` + `architecture` for any guardrail file (the list in `sb_agentkit.guardrails`,
     the same one the hooks enforce), so a PR that only loosens a check still gets both
     blocking reviewers;
   - `engineering` for any code change;
   - `performance` (advisory; pending, ADR-0017) for service runtime code and migrations, and
     for the `sb_db`, `sb_messaging`, `sb_workflows` and `sb_http` libraries.
   Other docs-only PRs get no AI review.
4. **Review jobs** run the repo's own `code-review` skill in CI mode through
   `anthropics/claude-code-action`, pinned by SHA. **Every blocking focus fails the gate on
   FAIL or BLOCKED**, including engineering; advisory findings alone can PASS. `performance` will be
   the one advisory focus (ADR-0017, not yet wired into triage): its job runs with `continue-on-error`, posts its findings
   on the PR, and never reaches the override check. Any `review-result.json`
   in the checkout is deleted before the reviewer starts. `sb-agentkit review-result` validates
   schema version 1, the exact checked-out commit, focus and finding fields. A blocking finding
   derives FAIL even if the reviewer declares PASS; malformed/missing evidence derives BLOCKED.
   The command prints the gate verdict on stdout (its exit status is not the gate decision).
   CI invokes the same validator as a standalone stdlib-only Python script: the credential-bearing
   review job does not install PR dependencies or create a `.venv` that activates local hooks.
   The workflow builds the PR summary comment from that JSON and applies the normalized verdict.
5. **Cache:** a PASS is cached, keyed on reviewer, exact checkout commit, diff, and a hash of
   `.claude/skills`, `.claude/agents`, `docs/conventions`, validator source and this workflow.
   Old verdict-only cache entries are not reused. A different checkout is re-reviewed.
6. **Override:** a blocking reviewer that doesn't PASS can be overridden only by the
   `override:ai-review` label, applied by someone whose repository role is admin or maintain.
   The flow: the owner applies the label, then uses **Re-run failed jobs** on the failed run
   (not "Re-run all jobs", which would re-run strip-override and clear the label).
   `.github/scripts/check-override.sh` then checks, through the issue events API, that the label
   is on the PR right now and that its latest application was by an admin/maintainer, so a
   self-applied label by an agent does nothing.

## Branch protection this relies on
The workflow is only a gate if `main` is protected:
- Required status checks: `ai-review-ok` and `ci-ok`.
- **Require review from Code Owners**, so every guardrail change needs an owner's approval.
- **Dismiss stale pull request approvals when new commits are pushed.**

The AI gate is not a boundary against a PR that edits the gate itself (this workflow, the
override script, the reviewer skill, or the validator under `tools/agentkit`): such a PR runs its
own version of them. CODEOWNERS is that boundary: those files are human-owned guardrails, and an
owner must approve the change. Schema validation is not an attestation from an independent
trusted execution environment. For hostile-contributor isolation, move the gate to a separately
protected workflow/policy revision before granting stronger credentials; do not claim that the
in-PR validator protects against edits to itself.

This needs the repository secret `ANTHROPIC_API_KEY`. Track the false-positive rate quarterly
(ADR-0016): a gate that cries wolf gets clicked through.

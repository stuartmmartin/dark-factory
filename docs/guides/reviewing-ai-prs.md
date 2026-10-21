# Reviewing an AI-written PR

Agents write most of the code; a human verifies the business logic. The structure exists so
that you can do that without reading everything: the rules of each operation are listed in one
place, each rule has a named test, the math has an acceptor, and the machines have already
checked everything that can be checked mechanically. This expands the four steps in
[clean architecture](../architecture/clean-architecture.md#reviewing-an-ai-written-change).

## What the machines already checked

Do not re-check these by hand; if one did not run, the PR is not ready (`ci-ok` must be green).

| Check | Where | What it proves |
|---|---|---|
| Tests, including every `test_R<n>_*` | `ci.yml` `test` (per affected member) | unit tests on fakes, contract suites on fakes and Postgres, integration tests on real Postgres, Kafka and Temporal |
| Rule coverage | `sb-checks` `use-case-rules` | every `R<n>` line has a `test_R<n>_*`, and no test names a rule that is not listed |
| Lint and format | ruff (`make lint`) | style, bugs, security lints; no float money, naive time or env reads (`sb-checks`) |
| Types | pyright (`make typecheck`) | strict in `domain` and `application` |
| Import contracts | import-linter, tach (`make contracts`) | layers point inward, the core imports no framework, services and libraries stay apart |
| Dependencies | deptry, `sb-graph check` | declared dependencies match imports; every member is registered |
| OpenAPI drift | `ci.yml` `openapi-drift` | the committed `contracts/openapi/*.json` matches the code |
| Migrations guard | `ci.yml` `migrations` | merged revisions are unchanged; round-trip, single head, no model drift |
| Kubernetes | `ci.yml` `k8s` (`make k8s-validate`) | manifests render and validate |
| Known CVEs | `ci.yml` `audit` (`pip-audit`) | no known vulnerability in the locked third-party dependencies |
| Environment setup | `ci.yml` `env-setup` | `docs/environment_setup.md` still works verbatim |
| AI review | `claude-review.yml` | all requested reviewers block on FAIL/BLOCKED; advisory findings alone may PASS |

## The four steps

1. **Read the rules.** Open each changed file in `application/use_cases/`. Its docstring lists
   `R1:`, `R2:`... Ask only: is this the business intent? Is a rule missing (a limit, a refusal,
   who may do it)? Is one wrong? A rule whose meaning changed needs your explicit approval;
   say so in the review.
2. **Check each rule is pinned.** Open the matching `tests/unit/use_cases/test_<name>.py`. For
   each `test_R<n>_*`, check the assertion would fail if the rule were broken: it asserts the
   effect (state, audit record, event, error), not merely that the call returned. A test that
   only checks "no exception" pins nothing.
3. **Try the math.** For a changed policy in `application/policies/`, open its acceptor in the
   admin (`http://localhost:<port>/admin`, the dev login from `.env`), enter a case whose answer
   you know (including an awkward one: zero, a negative, a currency without minor units), and
   compare. The page shows the policy version, so you know which code you tested.
4. **Skim the rest for thin interfaces (A8).** Routes, consumers and activities should only
   translate and call one use case. Anything that decides something belongs in a use case or a
   policy, where step 1 would have shown it.

Also stop and ask (do not approve) for: money rounding, tenancy or RLS, auth, audit behaviour,
a destructive migration, or a change to a guardrail file (CODEOWNERS will ask you anyway).

## `Disputed:` findings

When the agent believes a reviewer finding is a false positive, it lists it as
`Disputed: <rule> <path:line> — <reason>` instead of fixing it. For each one, open the cited
line and decide: if the finding is right, ask for the fix (the dispute does not count as a
PASS); if the reason holds, say so in the PR so the next reviewer does not reopen it. A
recurring false positive is worth an issue against the reviewer skill.

## Overriding the AI review

A blocking AI reviewer that does not PASS can be overridden only with the `override:ai-review`
label, applied by an admin or maintainer, followed by **Re-run failed jobs** on that run (see
[review gates](../agents/review-gates.md)). Use it when you have read the findings and accept the
risk, not to skip reading them; say why in a PR comment. The label is stripped on every new
push, so an override never carries over to code you have not seen.

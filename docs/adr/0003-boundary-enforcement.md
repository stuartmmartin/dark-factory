# ADR-0003: tach for packages, import-linter for layers, deptry for deps

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Agents write most of the code in this repo, so package and layer boundaries — "services may
depend on libs but never on other services", "`domain`/`application` may not import `sqlalchemy`
or `fastapi`" (spec §4.3) — need to be enforced by a machine, deterministically and fast, not by
review. The spec's original plan (§2 row 0003) was **tach** for cross-package boundaries,
**import-linter** for in-service CLEAN layers, and **deptry** for declared third-party
dependencies, with the spec's own risk table already naming the fallback: "tach maintenance after
its org move → import-linter can express the same package rules (ADR-0003 fallback)" (spec §12).

Building the first real tach policy (`tach.toml`, wiring `sb_checks` and `sb_graph` as modules
with `depends_on = []`) surfaced that the fallback is needed immediately, not just as a
contingency. With tach 0.35.1, every workspace member is installed as its own
**separately-distributed** uv workspace package. tach's `[[modules]] depends_on` policy only
governs modules within a single distribution's declared source roots; it has no concept of one
workspace distribution depending on another. An import of `sb_graph` from `sb_checks` (or vice
versa) is therefore classified the same way as an import of any third-party package — `tach
check` never flags it, even with `depends_on = []` declared on both sides. `tach check-external`
*does* fire on such an import, but only because it is checking a different question: whether the
import is declared in that member's `pyproject.toml [project].dependencies`. Declaring the
dependency would silence `check-external` even though the import still violates the "these two
packages must not depend on each other" policy — so `check-external` is a declaration-hygiene
check, not the policy enforcer.

## Decision
- **import-linter is the package-boundary policy enforcer**, in effect from day one rather than
  as a future fallback. Today its `independence` contract over the two tools
  (`root_packages = ["sb_checks", "sb_graph"]`; `root_packages` grows as `libs/py/sb_*` and
  `services/*` are added, and `sb-graph check` fails if a member is missing) is what actually
  stops a forbidden cross-package import, because it works from the AST and is not fooled by
  tach's distribution-external classification.
  The independence contract only fits peers that must not touch at all (like the two tools).
  Services and libs need *new* contracts, not an extension of this one: a `forbidden` contract
  so no service imports another service (and libs never import services), and a `layers`
  contract per service for its CLEAN layers (`interface` → `application` → `domain`, with
  `infrastructure` kept out of `domain`/`application`), plus `forbidden` contracts keeping
  `sqlalchemy`/`fastapi` out of `domain` and `application`.
- **`tach check-external`** is kept and run in `make contracts` as the declared-dependency hygiene
  check: it catches an import that is used in code but missing from that member's `pyproject.toml`
  dependencies, cross-package or third-party alike.
- **`tach check`** is kept, configured, and run, but is presently a no-op for cross-package policy
  for the reason above. It is retained for the day a single distribution grows internal
  submodules worth policing directly with tach's `[[modules]]` graph (for example, if a service's
  CLEAN layers are ever expressed as tach modules instead of, or in addition to, import-linter's
  `layers` contract).
- **deptry** continues to check that each member's third-party dependencies are declared and
  used; it is unaffected by this issue since it never reasoned about internal package edges.

`mk/contracts.mk`'s `contracts` target runs `tach check`, `tach check-external`, `lint-imports`
(import-linter), `sb-checks run`, then `deptry`, in that order, and CI's `preflight` job runs
`make contracts`.

## Consequences
The boundary policy is enforced correctly today: a forbidden cross-package import fails the build
via import-linter even though tach's `[[modules]]` graph cannot see it. The cost is running two
tools where the spec originally hoped one (tach) would cover both cross-package policy and
declaration hygiene, and keeping both configs (`tach.toml` and `[tool.importlinter]` in
`pyproject.toml`) in sync as new members are added — a human-owned, PreToolUse-guarded edit
either way (spec §7.2). Nothing here regresses if tach later adds cross-distribution policy
support; it only means `tach check` picks up real work it doesn't have yet.

## Revisit when
tach ships support for cross-distribution `[[modules]] depends_on` policy in a uv workspace, or
the workspace tools are consolidated into fewer distributions such that a single distribution's
internal modules become worth a `tach check` policy of their own.

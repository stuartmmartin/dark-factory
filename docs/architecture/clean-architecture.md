# Clean architecture in dark_factory

The goal is **reviewable business logic**. AI agents write most of the code, and humans verify
it. Everything below exists so that a reviewer can find and check every business rule in a
change without reading the plumbing.

## Where things live
See the layer model in [conventions/architecture.md](../conventions/architecture.md). In short:

| Question | Answer |
|---|---|
| Where is the business rule? | `application/use_cases/<verb>_<noun>.py` (process) or `application/policies/` (math) — A3 |
| How do I know every rule is tested? | The use case docstring lists `R1…Rn`; `sb-checks` fails if any `test_R<n>_*` is missing — A4, T2 |
| How can a human verify a calculation? | Policies are pure (A5) and exposed as SQLAdmin acceptors: type inputs, see outputs |
| What stops a shortcut through the layers? | import-linter contracts (A1, A2), run by `make contracts` and CI |
| Where are adapters wired? | `bootstrap.py` only — A7 |

## Enforcement matrix

| Rule | Mechanism | Runs in |
|---|---|---|
| A1, A2, A9, A10 | import-linter contracts in `.importlinter` | `make contracts`, CI preflight, Stop hook |
| A4, T2 | `sb-checks` `use-case-rules` | same |
| C3, C4, C5, C6, C11, T3 | `sb-checks` AST checks | same |
| C1 | pyright (strict in logic layers) | post-edit hook, `make typecheck`, CI |
| C13 | deptry + `sb-graph check` | `make contracts` (deptry) + `make graph-check` (sb-graph check), CI |
| A3, A5–A8, A11–A14 | code-review gate (rule IDs, evidence-bound) | `/review`, `claude-review.yml` |
| A15 | human-owned guardrail files | pre-edit hook, CODEOWNERS |

## Reviewing an AI-written change
1. Open the PR's use case and policy files. Read the `R<n>` list: is that the business intent?
2. Open the matching `tests/unit/use_cases/test_<name>.py`: does each `test_R<n>_*` pin the rule?
3. For calculations, run the SQLAdmin acceptor with a case you know the answer to.
4. Skim everything else only for A8 (thin interface). The machines have already checked the rest.

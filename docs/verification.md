# Verification matrix

`make check` is the local **code gate**, not a claim that every hosted CI job ran. Use locked
workspace dependencies when reproducing CI (`uv sync --all-packages --locked`).

| Gate | Local interface | In `make check`? | CI |
|---|---|---|---|
| Ruff lint/format | `make lint` | Yes | Preflight |
| Type checking | `make typecheck` | Yes | Typecheck |
| Import/AST/dependency/agent-doc contracts | `make contracts` | Yes | Preflight |
| Generated graph and complete service registration | `make graph-check` | Yes | Preflight |
| OpenAPI drift for every discovered service | `make openapi-check` | Yes | OpenAPI drift |
| Unit and integration tests | `make test` | Yes, whole workspace | Affected-member matrix |
| 100% statement/branch coverage of kernel/domain/application | `make coverage` | Yes | Required coverage job, whole workspace unit tests |
| Dependency vulnerability audit | `make audit` | No; network required | Audit, same command |
| Secret scan | `make secrets-check` | No; gitleaks required | Preflight, same command |
| Kubernetes render/schema validation | `make k8s-validate` | No; tools/schema access required | Kubernetes |
| Fresh database migration round-trip/model drift | `make db-check SVC=ledger` (repeat per service) | No; Docker required | Affected services with migrations |
| Merged migration immutability | Pre-edit hook provides local feedback | No | PR diff against base, including deletes/renames |
| Environment setup walkthrough | Follow [environment setup](environment_setup.md) in a disposable checkout | No; installs tools and starts infrastructure | Conditional documented-command execution, then teardown |
| Independent code review | `make review FOCUS=all`; inspect the actual verdict | No | Required requested review focuses |

`make check-fast` runs lint and affected unit tests. It omits contracts, graph validation, full
workspace tests, typechecking, OpenAPI and coverage; it is feedback, not the definition of done.
`make check` runs once per branch, before it goes into `main` (CI runs it on every PR).
The Stop hook uses the session baseline (or merge-base fallback) for affected selection and
includes committed and untracked inputs. Inspection failures are not interpreted as a clean tree.

Coverage includes unimported files and namespace packages. It writes `coverage.xml` and rejects
uncovered measured logic; passing tests alone is insufficient. Coverage.py's standard exclusions
still apply: review must reject pragmas/exclusions added merely to pass the gate. CI's `ci-ok`
depends on coverage.
Unexpected test warnings are errors; fix resource leaks/deprecations rather than hiding them.

Full tests need Docker and may download the Temporal test server. The coverage job runs only
non-integration tests and needs no Docker. Neither local rendering nor these development gates
constitutes a production deployment, identity integration, recovery exercise or security audit.
Those production concerns and broader demonstrations remain deferred.

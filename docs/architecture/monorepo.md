# Monorepo

## Layout

| Dir | Contains | Kind in the build graph |
|---|---|---|
| `libs/py/sb_*` | Shared platform libraries (Plan 3) | `lib` |
| `services/<name>` | Deployable services, each with its own `pyproject.toml` (Plan 4) | `service` |
| `tools/*` | Repo tooling: `sb-checks`, `sb-graph` | `tool` |
| `apps/*` | TypeScript apps (pnpm workspace), added when the first one arrives | `app` |
| `contracts/` | Language-neutral event schemas and OpenAPI snapshots (Plan 4) | — |

## One workspace, one lockfile

The repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with a
single `uv.lock`. Every member declares its own dependencies. Internal dependencies are declared
like any other (`"sb-kernel"`) and resolved through `[tool.uv.sources] … { workspace = true }`.
`make bootstrap` / `make sync` install every member in editable mode into one `.venv`.

## Make is the interface

Humans, agents and CI all use `make` targets; run `make help` to list them. Targets wrap the tools,
so tool choices can change without changing how anyone works. The Makefile stays compatible
with macOS make 3.81.

## Boundary enforcement

With uv 0.12.x, each workspace member (`sb_checks`, `sb_graph`, and later `libs/py/sb_*` and
`services/*`) is installed as its own **separately-distributed** package. tach 0.35.1's
`[[modules]] depends_on` policy is scoped to modules *within* a single distribution's declared
source roots — it does not see an import of one workspace distribution from another as an
internal `[[modules]]` edge at all; it classifies that import as *external* (third-party), the
same as importing `requests`. So `tach check` alone never flags a forbidden cross-package import,
even with `depends_on = []` declared for both sides. This was discovered building the tach.toml
policy for `sb_checks`/`sb_graph` (see ADR-0003) and is expected to hold for every future
cross-package edge in the workspace, not just this pair.

Given that, boundary enforcement is three tools. Their jobs overlap in part: a forbidden
cross-package import trips both import-linter (policy) and `tach check-external` (undeclared
dependency), and `tach check-external` and `sb-graph check` both compare imports with declared
dependencies. The overlap is deliberate belt-and-braces; the table says which one owns what:

| Tool | Question it answers | Config (human-owned) |
|---|---|---|
| **import-linter** | May this package depend on that one? This is the actual package-boundary **policy** enforcer today. Its `independence` contract fails the build the moment one workspace package imports another it isn't allowed to, regardless of what either member's `pyproject.toml` declares — it works from the AST, not from distribution metadata, so it isn't fooled by tach's external classification. | `[tool.importlinter]` in `pyproject.toml` |
| **tach check** | Inside one distribution, does a declared internal module depend only on its declared internal peers? Currently a no-op: every workspace member is one distribution with no internal `[[modules]]` beyond itself, so there is nothing for it to check yet. It stays configured (`tach.toml`) for the day a distribution grows internal submodules worth policing directly — for example, if a service's `domain`/`application`/`infrastructure`/`interface` packages are ever expressed as tach modules instead of import-linter layers. | `tach.toml` |
| **tach check-external** | Does every import a member's code actually uses appear as a declared dependency in that member's `pyproject.toml [project].dependencies`? This is the tach check that *does* fire on a cross-package import today, because tach sees the import as a third-party dependency and an undeclared one trips it. It is a hygiene check on declarations, not a policy check — declaring the dependency in `pyproject.toml` would silence it even for an import that policy forbids, which is exactly why import-linter carries the real rule. | `tach.toml` + the members' `pyproject.toml` |

Two more tools round out `make contracts`:

| Tool | Question it answers | Config (human-owned) |
|---|---|---|
| **deptry** | Are third-party deps declared and used? | the members' `pyproject.toml` |
| **sb-checks** | Rules linters can't express (no float in logic, rule↔test binding, …) | `tools/checks/allowlist.toml` |

`make contracts` runs, in order, `tach check`, `tach check-external`, `lint-imports`
(import-linter), `sb-checks run`, and `deptry` for every member (`mk/contracts.mk`). So does CI's
`preflight` job.

`sb-graph check` is not part of `make contracts`; it runs in `make graph-check` (pre-commit, CI
`preflight`, `make check`). Besides the drift check below, it asks: does each member's
`pyproject.toml [project].dependencies` declare exactly the workspace members its `src/` imports,
in both directions (nothing extra, nothing missing)?

## The build graph (ADR-0006, ADR-0007)

`tools/graph` (`sb-graph`) derives the graph from code. Nothing is maintained by hand:

- `make graph` writes `docs/generated/build-graph.json`, `build-graph.md` (Mermaid) and
  `module-index.md`. The module index lists each module's public API and one-line docstring
  summary, so agents can read it instead of opening files.
- `make graph-check` fails if those files are stale, if declared and actual dependencies
  disagree, or if there is a cycle. It runs in pre-commit and on every PR.
- `make graph-check` also fails if a member's `src/` is not covered by every root config: it must
  be under pytest `testpaths` and pyright `include` (`pyproject.toml`), listed in tach
  `source_roots` (`tach.toml`), and its import name must be in import-linter `root_packages`
  (`.importlinter` if present, else `[tool.importlinter]`). The error names the file to update,
  so a new member can't silently go untested, untyped or unpoliced.
- **Test edges.** A workspace member listed in another member's `[dependency-groups]` (any group,
  e.g. `test = ["sb-testkit"]`) is a *test edge*: it is not a runtime dependency, so the
  declared-vs-imported check ignores it, but `affected` and `blast-radius` follow it (changing
  `sb-testkit` re-runs the tests of everything that tests with it). Test edges appear as
  `test_depends_on` / `test_edges` in `build-graph.json` and as dotted `-.->` arrows in the
  Mermaid graph.
- `[tool.uv.workspace].exclude` globs are honoured, as uv does.
- `make affected`, `make blast-radius T=<member>` and `make deps T=<member>` answer "what does
  this change touch?" deterministically. CI's test matrix comes from `sb-graph affected`.
- A change to root config (`pyproject.toml`, `uv.lock`, `tach.toml`, `Makefile`, `mk/`,
  `.github/`, `mise.toml`, `conftest.py`) or to `contracts/` marks every member as affected.
  A file moved between members marks both (renames are split into delete + add).
- `make test PKG=<member>` exits 5 (pytest's "no tests collected") for a member with no tests yet.
  That is intentional: a member without tests should fail loudly, including in CI's matrix. The
  `test-unit` / `test-integration` / `test-affected-unit` targets tolerate exit 5 because a
  member may legitimately have no tests of that kind.

## Adding a language

- **TypeScript:** add `apps/` plus a pnpm workspace, and teach `sb_graph.workspace` to read
  `package.json` members (`kind = "app"`, `language = "typescript"`). Add `mk/ts.mk`.
- **Go:** add `go.work` at the root, with members under `services/` using `go.mod`. Teach `sb_graph`
  to read `go.mod` requires. Add `mk/go.mk`. Cross-language contracts go through `contracts/`.

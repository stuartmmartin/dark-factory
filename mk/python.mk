.PHONY: bootstrap sync fmt lint typecheck test test-unit test-integration mutate openapi openapi-check

ARGS ?=

bootstrap: ## Install pinned tools (mise), sync the workspace, install git hooks
	mise install
	$(UV) sync --all-packages
	$(UV) tool install --upgrade 'pyright[nodejs]' >/dev/null  # pyright-langserver on PATH for the Claude LSP plugin
	@if [ -f .pre-commit-config.yaml ]; then $(UV) run pre-commit install; fi

sync: ## Sync the uv workspace (all members)
	$(UV) sync --all-packages

fmt: ## Format code (ruff import sort + ruff format)
	$(UV) run ruff check --config ruff.toml --select I --fix .
	$(UV) run ruff format --config ruff.toml .

lint: ## Lint (ruff check + ruff format --check)
	$(UV) run ruff check --config ruff.toml .
	$(UV) run ruff format --config ruff.toml --check .

typecheck: ## Type-check with pyright
	$(UV) run pyright

test: ## Run tests: all, or PKG=<member dir or test file> (exit 5 = no tests yet, by design)
	$(UV) run pytest $(PKG) $(ARGS)

test-unit: ## Run non-integration tests (optionally PKG=...)
	$(UV) run pytest -m "not integration" $(PKG) $(ARGS) || test $$? -eq 5

test-integration: ## Run integration tests (optionally PKG=...)
	$(UV) run pytest -m integration $(PKG) $(ARGS) || test $$? -eq 5

mutate: ## Mutation-test a logic package: make mutate PKG=libs/py/sb_kernel (nightly; slow)
	@test -n "$(PKG)" || { echo "usage: make mutate PKG=<member>"; exit 2; }
	rm -rf $(PKG)/mutants; cd $(PKG) && $(UV) run mutmut run && $(UV) run mutmut results

openapi: ## Write each service's committed OpenAPI contract (contracts/openapi/<service>.json)
	@services=$$($(UV) run sb-graph members --kind service --format imports) || exit 1; \
	for svc in $$services; do $(UV) run sb-checks openapi --service $$svc --write || exit 1; done

openapi-check: ## Fail if a service's API has drifted from its committed OpenAPI contract
	@services=$$($(UV) run sb-graph members --kind service --format imports) || exit 1; \
	for svc in $$services; do $(UV) run sb-checks openapi --service $$svc --check || exit 1; done

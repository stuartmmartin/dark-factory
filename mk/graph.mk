.PHONY: graph graph-check affected blast-radius deps test-affected test-affected-unit

graph: ## Regenerate docs/generated (build graph + module index); commit the result
	$(UV) run sb-graph generate

graph-check: ## Fail if docs/generated is stale or declared deps disagree with imports
	$(UV) run sb-graph check

affected: ## List members affected vs BASE (default origin/main, else main)
	$(UV) run sb-graph affected --base $(BASE)

blast-radius: ## Everything that depends on T=<member> (transitively)
	@test -n "$(T)" || { echo "usage: make blast-radius T=<member>"; exit 2; }
	$(UV) run sb-graph blast-radius $(T)

deps: ## Everything T=<member> depends on (transitively)
	@test -n "$(T)" || { echo "usage: make deps T=<member>"; exit 2; }
	$(UV) run sb-graph deps $(T)

test-affected: ## Run all tests of affected members
	@paths="$$($(UV) run sb-graph affected --base $(BASE) --format paths)" || exit $$?; \
	if [ -z "$$paths" ]; then echo "no affected members"; else $(UV) run pytest $$paths $(ARGS); fi

test-affected-unit: ## Run non-integration tests of affected members
	@paths="$$($(UV) run sb-graph affected --base $(BASE) --format paths)" || exit $$?; \
	if [ -z "$$paths" ]; then echo "no affected members"; \
	else $(UV) run pytest -m "not integration" $$paths $(ARGS) || test $$? -eq 5; fi

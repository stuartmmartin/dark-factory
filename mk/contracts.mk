.PHONY: checks contracts deptry agent-lint

checks: ## Run AST convention checks (sb-checks)
	$(UV) run sb-checks run

deptry: ## Check each member's third-party deps are declared and used (deptry)
	@dirs=$$($(UV) run sb-graph members --format paths) || exit 1; \
	for dir in $$dirs; do \
		echo "deptry $$dir"; \
		(cd $$dir && $(UV) run deptry src) || exit 1; \
	done

agent-lint: ## Lint agent docs: frontmatter, rule-ID citations, links, AGENTS.md size
	$(UV) run sb-agentkit lint

contracts: ## Architecture contracts: tach + import-linter + sb-checks + deptry
	$(UV) run tach check
	$(UV) run tach check-external
	$(UV) run lint-imports
	$(MAKE) checks
	$(MAKE) deptry
	$(MAKE) agent-lint

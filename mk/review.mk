.PHONY: review

review: ## Run the code-review gate on this branch via the Claude CLI (FOCUS=all|security|architecture|engineering)
	@command -v claude >/dev/null || { echo "claude CLI not found; install Claude Code"; exit 2; }
	claude -p "/review $(or $(FOCUS),all)"

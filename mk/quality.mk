# Human-owned verification policy. All logic, including unimported modules, is measured.
.PHONY: coverage audit secrets-check
UVX ?= uvx
LOGIC_SOURCES := libs/py/sb_kernel/src $(wildcard services/*/src/*/domain services/*/src/*/application)

coverage: ## Unit tests plus 100% statement/branch coverage of kernel, domain and application
	@source=$$(printf '%s\n' $(LOGIC_SOURCES) | paste -sd , -); \
	$(UV) run coverage run --rcfile=.coveragerc --source="$$source" -m pytest -m 'not integration'
	$(UV) run coverage xml --rcfile=.coveragerc
	$(UV) run coverage report --rcfile=.coveragerc --fail-under=100

audit: ## Audit locked third-party dependencies (network required; same command as CI)
	@set -o pipefail; \
	$(UV) export --locked --all-packages --no-emit-workspace --quiet \
		| $(UVX) pip-audit@2.10.1 -r /dev/stdin --strict --disable-pip

secrets-check: ## Scan for secrets with gitleaks (same command as CI)
	gitleaks dir --redact --verbose .

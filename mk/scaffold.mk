# Generators (Copier templates in tools/templates). A new service still needs its boundary
# registration (services/<name>/REGISTER.md): tach.toml and .importlinter are human-owned (A15).
# NAME and SVC reach the recipe shells through the environment ("$$NAME"), never by expanding
# $(NAME) into the command text.
.PHONY: new-service new-use-case

export NAME SVC
NAME_RE := ^[a-z][a-z0-9_]*$$
# The interpreter the guards ask about keywords and standard-library modules.
SCAFFOLD_PYTHON ?= $(UV) run python
# compose/make names a service may not take (infra, the compose profiles) and `tests`.
RESERVED_NAMES := infra core init tools tests
# Existing services (for the A9 contract) and every member's import package.
PEER_SERVICES = $(notdir $(patsubst %/,%,$(wildcard services/*/)))
MEMBER_PACKAGES = $(notdir $(patsubst %/,%,$(wildcard libs/py/*/src/*/ tools/*/src/*/ services/*/src/*/)))
# The next free host port for a service API: one above the highest SB_*_API_PORT default in
# compose/services.yml (8001 when there is none yet, so the first service gets 8002). Two
# services generated before either is registered get the same port (REGISTER.md says so).
NEXT_API_PORT = $$(( $$( { echo 8001; grep -oE '_API_PORT:-[0-9]+' compose/services.yml 2>/dev/null | grep -oE '[0-9]+$$'; } | sort -n | tail -1) + 1 ))

new-service: ## Generate services/<NAME> from the service template: make new-service NAME=<snake>
	@test -n "$$NAME" || { echo "usage: make new-service NAME=<snake_case>"; exit 2; }
	@printf '%s\n' "$$NAME" | grep -Eq '$(NAME_RE)' || { echo "NAME must match $(NAME_RE), got '$$NAME'"; exit 2; }
	@test "$$(printf %s "$$NAME" | wc -c)" -le 24 || { echo "NAME must be at most 24 characters"; exit 2; }
	@for r in $(RESERVED_NAMES); do test "$$NAME" != "$$r" || { echo "NAME '$$NAME' is reserved (make/compose name or tests)"; exit 2; }; done
	@test ! -e "services/$$NAME" || { echo "services/$$NAME already exists"; exit 2; }
	@for m in $(MEMBER_PACKAGES); do test "$$NAME" != "$$m" || { echo "NAME '$$NAME' is already a workspace member"; exit 2; }; done
	@case "$$NAME" in sb_*) echo "NAME '$$NAME' is reserved for platform libraries (sb_*)"; exit 2;; esac
	@$(SCAFFOLD_PYTHON) -c 'import keyword, sys; n = sys.argv[1]; sys.exit(3 if keyword.iskeyword(n) or keyword.issoftkeyword(n) or n in sys.stdlib_module_names else 0)' "$$NAME"; \
	status=$$?; if [ $$status = 3 ]; then echo "NAME '$$NAME' is a Python keyword or standard-library module"; exit 2; elif [ $$status != 0 ]; then exit $$status; fi
	@contract=false; grep -q '^\[importlinter:contract:services-independent\]' .importlinter && contract=true; \
	set -x; $(UV) run copier copy --defaults --quiet -d name="$$NAME" -d api_port=$(NEXT_API_PORT) \
		-d peers="$(PEER_SERVICES)" -d taken="$(MEMBER_PACKAGES)" -d independence_contract=$$contract \
		tools/templates/service "services/$$NAME"
	@echo; cat "services/$$NAME/REGISTER.md"; echo
	$(UV) sync --all-packages
	$(MAKE) graph
	@echo "services/$$NAME generated. Paste the REGISTER.md snippets above (tach.toml and .importlinter are human-owned), then run make check."

new-use-case: ## Generate a use case and its RED rule test: make new-use-case SVC=<svc> NAME=<verb_noun>
	@test -n "$$SVC" -a -n "$$NAME" || { echo "usage: make new-use-case SVC=<service> NAME=<verb_noun>"; exit 2; }
	@printf '%s\n' "$$NAME" | grep -Eq '$(NAME_RE)' || { echo "NAME must match $(NAME_RE), got '$$NAME'"; exit 2; }
	@printf '%s\n' "$$SVC" | grep -Eq '$(NAME_RE)' || { echo "SVC must match $(NAME_RE), got '$$SVC'"; exit 2; }
	@test -d "services/$$SVC/src/$$SVC/application/use_cases" || { echo "no service '$$SVC' (services/$$SVC/src/$$SVC/application/use_cases)"; exit 2; }
	@test ! -e "services/$$SVC/src/$$SVC/application/use_cases/$$NAME.py" || { echo "use case services/$$SVC/src/$$SVC/application/use_cases/$$NAME.py already exists"; exit 2; }
	@test ! -e "services/$$SVC/tests/unit/use_cases/test_$$NAME.py" || { echo "services/$$SVC/tests/unit/use_cases/test_$$NAME.py already exists"; exit 2; }
	@set -x; $(UV) run copier copy --defaults --quiet -d svc="$$SVC" -d name="$$NAME" tools/templates/use_case "services/$$SVC"
	@echo "Next: write the R<n> lines in services/$$SVC/src/$$SVC/application/use_cases/$$NAME.py, then run"
	@echo "  make test PKG=services/$$SVC/tests/unit/use_cases/test_$$NAME.py   (RED by design, T1)"

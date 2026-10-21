# Local environment. `make up infra` starts the appliances; `make up <svc...>` ensures infra is
# up and healthy first, runs each service's migrations, then starts its processes (the API
# hot-reloads; the worker and consumer do not, so `make restart <svc>` picks up their edits).
COMPOSE_PROJECT_NAME ?= sb-$(notdir $(CURDIR))
export COMPOSE_PROJECT_NAME
ENV_FILE := $(if $(wildcard .env),.env,.env.example)

# Every checkout runs its own stack side by side: the project name keeps containers and volumes
# apart, and a linked worktree shifts each SB_*_PORT default in compose/*.yml by SB_PORT_OFFSET.
# The offset is a multiple of 20 from 20 to 800, taken from the worktree's path. The main checkout
# keeps offset 0. Steps of 20 up to 800 mean no worktree's port can equal another port kind's
# (5432, 7233, 8001, 8080, 8233, 9092). On a clash, set SB_PORT_OFFSET or a single SB_*_PORT.
# `make ports` prints this checkout's ports.
GIT_DIR := $(shell git rev-parse --absolute-git-dir 2>/dev/null)
GIT_COMMON_DIR := $(shell git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
SB_PORT_OFFSET ?= $(if $(filter $(GIT_COMMON_DIR),$(GIT_DIR)),0,$(shell echo $$(( ($$(printf %s "$(CURDIR)" | cksum | cut -d' ' -f1) % 40 + 1) * 20 ))))
PORT_DEFAULTS := $(shell grep -ohE 'SB_[A-Z0-9_]+_PORT:-[0-9]+' compose/*.yml 2>/dev/null | sort -u)
ifneq ($(SB_PORT_OFFSET),0)
  $(foreach d,$(PORT_DEFAULTS),$(eval $(word 1,$(subst :-, ,$(d))) ?= $(shell echo $$(( $(word 2,$(subst :-, ,$(d))) + $(SB_PORT_OFFSET) ))))$(eval export $(word 1,$(subst :-, ,$(d)))))
endif
COMPOSE ?= docker compose -f compose/docker-compose.yml $(if $(wildcard compose/services.yml),-f compose/services.yml) --env-file $(ENV_FILE)
SERVICES ?= $(notdir $(patsubst %/,%,$(wildcard services/*/)))

# A service's depends_on names infra services (profile core), so every invocation that loads a
# service profile also passes `--profile core`, or compose rejects the project.
# `make up ledger` / `make logs ledger` / `make restart ledger`: treat the extra goals as names, and swallow them.
NAME_GOALS := up logs build restart
ifneq ($(filter $(firstword $(MAKECMDGOALS)),$(NAME_GOALS)),)
  NAMES := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(NAMES),)
    $(eval $(NAMES):;@:)
  endif
endif
APP_NAMES = $(filter-out infra,$(NAMES))
# The <svc>-api/-worker/-consumer processes that compose actually defines: a service gets its
# worker or consumer only with that seam, and naming an undefined service fails the command.
# Sets `procs` in the recipe shell (newline-separated).
APP_PROCESSES = $(foreach s,$(APP_NAMES),$(s)-api $(s)-worker $(s)-consumer)
DEFINED_PROCESSES = defined=$$($(COMPOSE) --profile '*' config --services) || exit 1; \
	procs=$$(for p in $(APP_PROCESSES); do echo "$$defined" | grep -qx "$$p" && echo "$$p"; done)

.PHONY: up down logs ps ports build restart seed up-tools reset doctor _validate-names

_validate-names:
	@for n in $(NAMES); do \
		if [ "$$n" != infra ] && ! echo " $(SERVICES) " | grep -q " $$n "; then \
			echo "unknown service '$$n'. valid names: infra $(SERVICES)"; exit 2; \
		fi; \
	done

up: _validate-names ## make up infra | make up <svc...> (infra is always started first)
	@if [ -z "$(NAMES)" ]; then \
		echo "usage: make up infra | make up <service...>"; echo "services: $(SERVICES)"; \
	else \
		$(COMPOSE) --profile core up -d --wait || exit 1; \
		$(COMPOSE) --profile init run --rm kafka-init || exit 1; \
		for s in $(APP_NAMES); do \
			$(COMPOSE) --profile core --profile $$s-migrate run --rm --build $$s-migrate || exit 1; \
			$(COMPOSE) --profile core --profile $$s up -d --build --wait || exit 1; \
		done; \
	fi

down: ## Stop everything (keeps volumes)
	$(COMPOSE) --profile '*' down

logs: _validate-names ## Follow logs: all, or make logs <svc...>
	@procs=; if [ -n "$(APP_NAMES)" ]; then $(DEFINED_PROCESSES); fi; \
	$(COMPOSE) --profile '*' logs -f --tail=100 $$procs

ps: ## Show running containers
	$(COMPOSE) --profile '*' ps

ports: ## This checkout's compose project and host ports (worktrees are offset from the main checkout)
	@echo "COMPOSE_PROJECT_NAME=$(COMPOSE_PROJECT_NAME) SB_PORT_OFFSET=$(SB_PORT_OFFSET)"
	@for d in $(PORT_DEFAULTS); do \
		name=$${d%%:-*}; value=$$(printenv "$$name" || sed -n "s/^$$name=//p" $(ENV_FILE)); \
		echo "$$name=$${value:-$${d##*:-}}"; \
	done

build: _validate-names ## Rebuild images for services (after uv.lock changes)
	$(COMPOSE) --profile core $(foreach s,$(APP_NAMES),--profile $(s) --profile $(s)-migrate) build

restart: _validate-names ## Restart a service's processes to pick up edits: make restart ledger
	@test -n "$(APP_NAMES)" || { echo "usage: make restart <service...>  (services: $(SERVICES))"; exit 2; }
	@$(DEFINED_PROCESSES); \
	if [ -z "$$procs" ]; then \
		echo "no processes to restart for $(APP_NAMES) (compose defines none of $(APP_PROCESSES)); run make up $(APP_NAMES) first"; exit 2; \
	fi; \
	$(COMPOSE) --profile core $(foreach s,$(APP_NAMES),--profile $(s)) restart $$procs

# The seed runs inside the API container, so it blanks the admin credentials it would inherit
# from the API's environment (only the API mounts the admin).
seed: ## Seed demo data into a running service: make seed SVC=ledger
	@test -n "$$SVC" || { echo "usage: make seed SVC=<service>  (services: $(SERVICES))"; exit 2; }
	@P=$$(printf '%s' "$$SVC" | tr '[:lower:]' '[:upper:]'); \
	set -x; $(COMPOSE) --profile core --profile "$$SVC" exec -e "$${P}_ADMIN_USERNAME=" \
		-e "$${P}_ADMIN_PASSWORD=" -e "$${P}_ADMIN_SECRET_KEY=" "$$SVC-api" python -m "$$SVC.seed"

up-tools: ## Start dev tools (Kafka UI)
	$(COMPOSE) --profile tools up -d

reset: ## Remove all containers AND volumes (asks; CONFIRM=1 to skip)
	@if [ "$(CONFIRM)" != 1 ]; then \
		if [ -t 0 ]; then read -r -p "Delete all local data volumes? [y/N] " a; [ "$$a" = y ] || exit 1; \
		else echo "refusing to delete volumes non-interactively; re-run with CONFIRM=1"; exit 1; fi; \
	fi
	$(COMPOSE) --profile '*' down -v

doctor: ## Diagnose the local environment (tools, Docker, ports)
	$(UV) run --env-file $(ENV_FILE) sb-checks doctor --compose "$(COMPOSE)"

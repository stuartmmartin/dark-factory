# dark-factory — the only interface for humans, agents and CI. Run `make help`.
# Must stay compatible with macOS make 3.81 (no .SHELLFLAGS / .ONESHELL).
SHELL := /bin/bash
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

UV ?= uv
PKG ?=
BASE ?= $(shell git rev-parse --verify --quiet origin/main >/dev/null 2>&1 && echo origin/main || echo main)

include $(wildcard mk/*.mk)

.PHONY: help
help: ## Show all targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort

.PHONY: check check-fast

check-fast: lint test-affected-unit ## Fast feedback (Stop hook): lint and affected unit tests

check: lint typecheck contracts graph-check openapi-check test coverage ## Full local gate before merging to main (tests, coverage, types, contracts, OpenAPI); see docs/verification.md

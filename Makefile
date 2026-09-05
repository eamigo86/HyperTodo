SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
MOBILE_DIR := mobile
NVM_DIR ?= $(HOME)/.nvm
NVM_SH := $(NVM_DIR)/nvm.sh
YARN := COREPACK_HOME="$(CURDIR)/$(MOBILE_DIR)/.corepack" corepack yarn
REDIS_URL ?= redis://127.0.0.1:6379/15
EXPO_PUBLIC_API_URL ?= http://127.0.0.1:8000/hv/

define run_mobile
	cd "$(MOBILE_DIR)" && \
		export NVM_DIR="$(NVM_DIR)" && \
		source "$(NVM_SH)" && \
		nvm use --silent && \
		$(1)
endef

.PHONY: help setup test check \
	backend-install backend-migrate backend-seed backend-run backend-run-redis \
	backend-test backend-test-redis backend-lint backend-check backend-quality \
	mobile-install mobile-start mobile-start-android mobile-test mobile-typecheck \
	mobile-doctor mobile-check mobile-ios mobile-android acceptance

help: ## List available commands and their descriptions.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<command>\033[0m\n\nCommands:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n"

setup: backend-install mobile-install ## Install backend and mobile dependencies.

test: backend-test mobile-test ## Run all automated backend and mobile tests.

check: backend-quality mobile-check ## Run every automated project quality gate.

backend-install: ## Install locked Python dependencies with uv.
	@cd "$(BACKEND_DIR)" && uv sync

backend-migrate: ## Apply Django and dj-hyperview database migrations.
	@cd "$(BACKEND_DIR)" && uv run python manage.py migrate

backend-seed: ## Create idempotent demo data; requires HYPERTODO_DEMO_PASSWORD.
	@if [[ -z "$(HYPERTODO_DEMO_PASSWORD)" ]]; then \
		echo "HYPERTODO_DEMO_PASSWORD is required."; \
		exit 1; \
	fi
	@cd "$(BACKEND_DIR)" && \
		HYPERTODO_DEMO_PASSWORD="$(HYPERTODO_DEMO_PASSWORD)" \
		uv run python manage.py seed_demo

backend-run: ## Start Django with the default local-memory cache.
	@cd "$(BACKEND_DIR)" && uv run python manage.py runserver 0.0.0.0:8000

backend-run-redis: ## Start Django using the existing Redis development database.
	@cd "$(BACKEND_DIR)" && \
		ENABLE_REDIS_CACHE=1 REDIS_URL="$(REDIS_URL)" \
		uv run python manage.py runserver 0.0.0.0:8000

backend-test: ## Run backend tests with branch-aware coverage enforcement.
	@cd "$(BACKEND_DIR)" && uv run pytest

backend-test-redis: ## Run the isolated integration test against Redis database 14.
	@cd "$(BACKEND_DIR)" && uv run pytest -m redis

backend-lint: ## Run Ruff lint checks for backend code and tests.
	@cd "$(BACKEND_DIR)" && uv run ruff check .

backend-check: ## Run Django checks and verify that migrations are current.
	@cd "$(BACKEND_DIR)" && uv run python manage.py check
	@cd "$(BACKEND_DIR)" && uv run python manage.py makemigrations --check --dry-run

backend-quality: backend-lint backend-test backend-check ## Run every backend quality gate.

mobile-install: ## Install locked mobile dependencies with Node and Corepack.
	@$(call run_mobile,$(YARN) install --frozen-lockfile)

mobile-start: ## Start Metro for iOS or a physical device using EXPO_PUBLIC_API_URL.
	@$(call run_mobile,EXPO_PUBLIC_API_URL="$(EXPO_PUBLIC_API_URL)" $(YARN) start)

mobile-start-android: ## Start Metro with the Android Emulator backend address.
	@$(call run_mobile,EXPO_PUBLIC_API_URL="http://10.0.2.2:8000/hv/" $(YARN) start)

mobile-test: ## Run focused Jest tests for the owned mobile shell.
	@$(call run_mobile,$(YARN) test)

mobile-typecheck: ## Run strict TypeScript validation without producing a build.
	@$(call run_mobile,$(YARN) typecheck)

mobile-doctor: ## Validate the Expo dependency and configuration matrix.
	@$(call run_mobile,$(YARN) doctor)

mobile-check: mobile-typecheck mobile-test mobile-doctor ## Run every automated mobile quality gate.

mobile-ios: ## Create or launch the iOS development build for manual acceptance.
	@$(call run_mobile,$(YARN) ios)

mobile-android: ## Create or launch the Android development build for manual acceptance.
	@$(call run_mobile,$(YARN) android)

acceptance: ## Display the manual iOS and Android acceptance checklist.
	@cat doc/acceptance.md

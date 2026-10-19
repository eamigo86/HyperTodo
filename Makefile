SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
MOBILE_DIR := mobile
# mobile/.nvmrc is the one place that pins Node; CI reads it too.
NODE_VERSION := $(strip $(shell cat $(MOBILE_DIR)/.nvmrc))
NVM_DIR ?= $(HOME)/.nvm
NVM_SH := $(NVM_DIR)/nvm.sh
YARN := COREPACK_HOME="$(CURDIR)/$(MOBILE_DIR)/.corepack" corepack yarn
REDIS_URL ?= redis://127.0.0.1:6379/15
REDIS_TEST_URL ?= redis://127.0.0.1:6379/14
DJANGO_DEBUG ?= 1
EXPO_PUBLIC_API_URL ?= http://127.0.0.1:8000/hv/
# The Android Emulator reaches the host's loopback as 10.0.2.2.
EMULATOR_API_URL := http://10.0.2.2:8000/hv/
# Validation only, as in CI: Expo Doctor resolves the app config, which needs an https
# URL. Nothing connects to this host.
DOCTOR_API_URL ?= https://hypertodo-ci.invalid/hv/
# mobile/app.config.ts refuses cleartext HTTP, and a missing URL, without this opt-in.
LOCAL_API := EXPO_PUBLIC_ALLOW_LOCAL_API=1
# $(if) splits its arguments at every comma, so a literal one is spelled through this.
comma := ,

# One application/settings and ASGI launcher; targets only choose cache/bind policy.
define run_backend
	DJANGO_SETTINGS_MODULE=config.settings REDIS_URL="$(REDIS_URL)" \
		uv run python -m uvicorn config.asgi:application \
		--host "$(1)" --port 8000 \
		--loop asyncio --http h11 --ws none --no-proxy-headers
endef

# Run a command on the pinned Node, loaded through nvm; say what is missing if it fails.
define with_node
	export NVM_DIR="$(NVM_DIR)" && \
		{ [[ -s "$(NVM_SH)" ]] || { echo "nvm not found at $(NVM_SH): install nvm or set NVM_DIR." >&2; exit 1; }; } && \
		source "$(NVM_SH)" && \
		{ nvm use --silent "$(NODE_VERSION)" || { echo "Node $(NODE_VERSION) missing: run 'nvm install' in $(MOBILE_DIR)/" >&2; exit 1; }; } && \
		$(1)
endef

define run_mobile
	cd "$(MOBILE_DIR)" && \
		$(call with_node,$(1))
endef

.PHONY: help setup test check \
	backend-install backend-migrate backend-seed backend-run backend-run-redis \
	backend-run-device backend-run-sse \
	backend-test backend-test-editor backend-test-redis backend-lint backend-check backend-quality \
	mobile-install mobile-start mobile-start-android mobile-test mobile-test-coverage mobile-typecheck \
	mobile-start-device mobile-start-go mobile-login mobile-whoami \
	mobile-doctor mobile-check mobile-ios mobile-ios-device \
	mobile-android mobile-android-device lan-ip acceptance

help: ## List available commands and their descriptions.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<command>\033[0m\n\nCommands:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n"

setup: backend-install mobile-install ## Install backend and mobile dependencies.

test: backend-test mobile-test ## Run the backend pytest and mobile Jest suites.

check: backend-quality mobile-check ## Run every automated project quality gate.

backend-install: ## Install locked Python dependencies with uv.
	@cd "$(BACKEND_DIR)" && uv sync --locked

backend-migrate: ## Apply Django and dj-hyperview database migrations.
	@cd "$(BACKEND_DIR)" && uv run python manage.py migrate

backend-seed: ## Create or reset the admin and demo accounts with sample data.
	@cd "$(BACKEND_DIR)" && \
		DJANGO_DEBUG="$(DJANGO_DEBUG)" \
		HYPERTODO_ADMIN_PASSWORD="$(HYPERTODO_ADMIN_PASSWORD)" \
		HYPERTODO_DEMO_PASSWORD="$(HYPERTODO_DEMO_PASSWORD)" \
		uv run python manage.py seed_demo

backend-run: ## Start ASGI/SSE on loopback without the template cache; Redis must exist.
	@cd "$(BACKEND_DIR)" && $(call run_backend,127.0.0.1)

backend-run-redis: ## Start ASGI/SSE on loopback with the Redis template cache.
	@cd "$(BACKEND_DIR)" && ENABLE_REDIS_CACHE=1 $(call run_backend,127.0.0.1)

backend-run-device: ## Start Redis-backed ASGI/SSE on all interfaces for a device; requires LAN_IP.
	@if [[ -z "$(LAN_IP)" ]]; then echo "LAN_IP is required. Run make lan-ip."; exit 1; fi
	@cd "$(BACKEND_DIR)" && \
		ENABLE_REDIS_CACHE=1 \
		DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost,$(LAN_IP)" \
		CSRF_TRUSTED_ORIGINS="http://127.0.0.1:8000,http://$(LAN_IP):8000" \
		$(call run_backend,0.0.0.0)

backend-run-sse: ## Start the same ASGI/SSE app on loopback or optional LAN_IP.
	@cd "$(BACKEND_DIR)" && \
		DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost,10.0.2.2$(if $(LAN_IP),$(comma)$(LAN_IP))" \
		CSRF_TRUSTED_ORIGINS="http://127.0.0.1:8000,http://10.0.2.2:8000$(if $(LAN_IP),$(comma)http://$(LAN_IP):8000)" \
		$(call run_backend,$(if $(LAN_IP),$(LAN_IP),127.0.0.1))

backend-test: ## Run backend tests with branch-aware coverage enforcement.
	@cd "$(BACKEND_DIR)" && uv run pytest

backend-test-editor: ## Exercise the installed Admin formatter with a real HXML screen.
	@cd "$(BACKEND_DIR)" && \
		HXML_EDITOR_JS="$$(uv run python -c 'from importlib.resources import files; print(files("dj_hyperview").joinpath("static/dj_hyperview/admin/hxml_editor.js"))')" && \
		export HXML_EDITOR_JS && \
		$(call with_node,node --test tests/js/*.mjs)

backend-test-redis: ## Run the opt-in Redis tests; needs an owned disposable Redis.
	@cd "$(BACKEND_DIR)" && \
		HYPERTODO_REDIS_INTEGRATION=1 \
		HYPERTODO_REDIS_TEST_URL="$(REDIS_TEST_URL)" \
		uv run pytest -m redis --no-cov

backend-lint: ## Run Ruff lint and format checks for backend code and tests.
	@cd "$(BACKEND_DIR)" && uv run ruff check . && uv run ruff format --check .

backend-check: ## Run Django checks and verify that migrations are current.
	@cd "$(BACKEND_DIR)" && uv run python manage.py check
	@cd "$(BACKEND_DIR)" && uv run python manage.py makemigrations --check --dry-run

backend-quality: backend-lint backend-test backend-test-editor backend-check ## Run every backend quality gate.

mobile-install: ## Install locked mobile dependencies with Node and Corepack.
	@$(call run_mobile,$(YARN) install --frozen-lockfile)

mobile-start: ## Start Metro for the development client; EXPO_PUBLIC_API_URL defaults to the local backend.
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="$(EXPO_PUBLIC_API_URL)" $(YARN) start)

mobile-start-android: ## Start Metro with the Android Emulator backend address.
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="$(EMULATOR_API_URL)" $(YARN) start)

mobile-start-device: ## Start Metro for a physical device; requires LAN_IP.
	@if [[ -z "$(LAN_IP)" ]]; then echo "LAN_IP is required. Run make lan-ip."; exit 1; fi
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="http://$(LAN_IP):8000/hv/" $(YARN) start)

mobile-start-go: ## Start local Expo Go QR workflow; requires LAN_IP.
	@if [[ -z "$(LAN_IP)" ]]; then echo "LAN_IP is required. Run make lan-ip."; exit 1; fi
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="http://$(LAN_IP):8000/hv/" $(YARN) start:go)

mobile-login: ## Sign in to Expo CLI through the browser.
	@$(call run_mobile,$(YARN) expo login --browser)

mobile-whoami: ## Display the Expo account used by the CLI.
	@$(call run_mobile,$(YARN) expo whoami)

mobile-test: ## Run the mobile Jest suite.
	@$(call run_mobile,$(YARN) test)

mobile-test-coverage: ## Enforce 95% coverage across all owned mobile code.
	@$(call run_mobile,$(YARN) test:coverage)

mobile-typecheck: ## Run strict TypeScript validation without producing a build.
	@$(call run_mobile,$(YARN) typecheck)

mobile-doctor: ## Run Expo Doctor against a validation-only API URL (needs network access).
	@$(call run_mobile,EXPO_PUBLIC_ALLOW_LOCAL_API=0 EXPO_PUBLIC_API_URL="$(DOCTOR_API_URL)" $(YARN) doctor)

mobile-check: mobile-typecheck mobile-test-coverage mobile-doctor ## Run every automated mobile quality gate.

mobile-ios: ## Build and launch the iOS development app on a Simulator.
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="$(EXPO_PUBLIC_API_URL)" $(YARN) ios)

mobile-ios-device: ## Build and install HyperTodo on an iPhone; requires LAN_IP.
	@if [[ -z "$(LAN_IP)" ]]; then echo "LAN_IP is required. Run make lan-ip."; exit 1; fi
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="http://$(LAN_IP):8000/hv/" $(YARN) expo run:ios --device)

mobile-android: ## Build and launch the Android development app on an emulator.
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="$(EMULATOR_API_URL)" $(YARN) android)

mobile-android-device: ## Build and install HyperTodo on Android; requires LAN_IP.
	@if [[ -z "$(LAN_IP)" ]]; then echo "LAN_IP is required. Run make lan-ip."; exit 1; fi
	@$(call run_mobile,$(LOCAL_API) EXPO_PUBLIC_API_URL="http://$(LAN_IP):8000/hv/" $(YARN) expo run:android --device)

lan-ip: ## Print the macOS default-route address (en0, else another en* one, behind a VPN), a candidate LAN IP.
	@iface="$$(route -n get default 2>/dev/null | awk '/interface:/ { print $$2; exit }')"; \
		case "$$iface" in utun*|ppp*) \
			iface=; \
			for n in en0 $$(ifconfig -l); do \
				[[ "$$n" == en* ]] || continue; \
				a="$$(ipconfig getifaddr "$$n" 2>/dev/null)"; \
				[[ -n "$$a" && "$$a" != 169.254.* ]] && { iface="$$n"; break; }; \
			done;; \
		esac; \
		ip="$$(ipconfig getifaddr "$$iface" 2>/dev/null)" && [[ -n "$$ip" ]] && echo "$$ip" \
		|| { echo "No LAN address found; inspect network settings." >&2; exit 1; }

acceptance: ## Display the manual iOS and Android acceptance checklist.
	@printf '%s\n' \
		'Manual acceptance checklist:' \
		'  [ ] Branded splash and loading states render correctly.' \
		'  [ ] Login persists the Django session and isolates data by user.' \
		'  [ ] Tasks can be created, edited, completed, reopened, filtered, and deleted.' \
		'  [ ] Categories can be created, edited, filtered, and deleted.' \
		'  [ ] Invalid forms show field-level HXML feedback.' \
		'  [ ] Light/dark themes and English/Spanish render correctly.' \
		'  [ ] Avatar selection and biometric enrollment behave correctly.' \
		'  [ ] Database-backed About and Categories templates refresh after editing.' \
		'  [ ] Repeat the flow on iOS and Android before a release.'

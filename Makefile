.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

# Ports come from .env when it exists, so the banner cannot print a stale one.
env_or = $(shell grep -E '^$(1)=' .env 2>/dev/null | cut -d= -f2- | grep . || echo $(2))
WEB_PORT := $(call env_or,WEB_PORT,8080)
API_PORT := $(call env_or,API_PORT,8000)
ADMIN_USER := $(call env_or,SEED_ADMIN_USERNAME,admin)
ADMIN_PASS := $(call env_or,SEED_ADMIN_PASSWORD,admin)

# Colours, but only when stdout is a terminal.
ifneq (,$(findstring xterm,$(TERM)))
  BOLD := $(shell tput bold)
  DIM := $(shell tput dim)
  AMBER := $(shell tput setaf 3)
  RESET := $(shell tput sgr0)
endif

.PHONY: help up down logs migrate migration test lint reset seed dev ps shell-api shell-db

help: ## Show this help
	@echo "$(BOLD)Pelita$(RESET) — provider-agnostic chatbot template"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(AMBER)%-12s$(RESET) %s\n", $$1, $$2}'
	@echo

.env: ## Create .env from the example on first run
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo "$(AMBER)Created .env from .env.example.$(RESET) Set LLM_API_KEY before chatting."; \
	fi

up: .env ## Build and start everything, run migrations, seed admin
	@$(COMPOSE) up -d --build --wait
	@$(MAKE) --no-print-directory _banner

_banner:
	@echo
	@echo "  $(BOLD)Pelita is running$(RESET)"
	@echo "  ─────────────────────────────────────────"
	@echo "  Web        $(AMBER)http://localhost:$(WEB_PORT)$(RESET)"
	@echo "  API docs   $(DIM)http://localhost:$(API_PORT)/api/docs$(RESET)"
	@echo
	@echo "  Sign in with"
	@echo "    username  $(BOLD)$(ADMIN_USER)$(RESET)"
	@echo "    password  $(BOLD)$(ADMIN_PASS)$(RESET)"
	@echo
	@echo "  $(DIM)Change these before deploying anywhere.$(RESET)"
	@echo

down: ## Stop everything, keep the database
	@$(COMPOSE) down

logs: ## Follow logs from all services
	@$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	@$(COMPOSE) ps

migrate: ## Apply pending migrations
	@$(COMPOSE) exec api alembic upgrade head

migration: ## Autogenerate a migration — make migration m="add widgets"
	@test -n "$(m)" || { echo 'Usage: make migration m="what changed"'; exit 1; }
	@$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

seed: ## Re-run the seed (idempotent)
	@$(COMPOSE) exec api python -m app.scripts.seed

# Frontend tooling runs in a container so `make test` needs Docker and nothing
# else. The named volume keeps node_modules between runs.
NODE := docker run --rm -v "$(PWD)/frontend:/app" -v pelita-node-modules:/app/node_modules \
	-w /app node:22-alpine sh -c

# Source is mounted rather than baked in, so test and lint see your edits
# without a rebuild.
PY_RUN := $(COMPOSE) run --rm --entrypoint="" -v "$(PWD)/backend:/srv" api

test: ## Run backend and frontend tests
	@$(PY_RUN) python -m pytest -q --cov=app --cov-report=term-missing
	@$(NODE) "npm install --silent --no-audit --no-fund && npm test"

lint: ## Lint backend and frontend
	@$(PY_RUN) python -m ruff check app tests
	@$(NODE) "npm install --silent --no-audit --no-fund && npm run lint"

dev: .env ## Run with hot reload on both sides
	@$(COMPOSE_DEV) up -d --build --wait db api
	@echo "$(AMBER)API on http://localhost:$(API_PORT)$(RESET) reloads on save — starting Vite with HMR"
	@cd frontend && npm install && npm run dev

api-dev: .env ## API only, with hot reload (no Vite)
	@$(COMPOSE_DEV) up -d --build --wait db api
	@echo "$(AMBER)API on http://localhost:$(API_PORT)$(RESET) — reloads on save"

reset: ## Destroy everything including the database, then start clean
	@echo "$(BOLD)This deletes the database volume.$(RESET)"
	@read -p "  Type 'yes' to continue: " ok && [ "$$ok" = "yes" ] || exit 1
	@$(COMPOSE) down -v --remove-orphans
	@$(MAKE) --no-print-directory up

shell-api: ## Shell into the API container
	@$(COMPOSE) exec api bash

shell-db: ## psql into the database
	@$(COMPOSE) exec db psql -U $${POSTGRES_USER:-pelita} -d $${POSTGRES_DB:-pelita}

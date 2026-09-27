COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help up down logs ps migrate test test-backend test-frontend lint typecheck e2e api-types

help: ## List available commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-15s %s\n", $$1, $$2}'

up: ## Build and start the whole stack
	$(COMPOSE) up --build --renew-anon-volumes

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f

ps: ## Show service health
	$(COMPOSE) ps

migrate: ## Apply database migrations
	$(COMPOSE) run --rm migrate

test: test-backend test-frontend ## Run all unit and integration tests

test-backend: ## Backend tests inside the container (PostgreSQL and Redis included)
	$(COMPOSE) run --rm backend pytest

test-frontend: ## Frontend unit and component tests
	cd frontend && npm test

lint: ## Lint and format checks
	$(COMPOSE) run --rm backend sh -c "ruff check . && ruff format --check ."
	cd frontend && npm run lint && npm run format:check

typecheck: ## Static type checks
	$(COMPOSE) run --rm backend mypy
	cd frontend && npm run typecheck

e2e: ## Browser tests against the running stack
	cd frontend && E2E_BASE_URL=http://localhost:3000 npm run e2e

api-types: ## Regenerate frontend API types from the backend schema
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/frontend:/out" backend python -m app.export_openapi /out/openapi.json
	cd frontend && npm run api:types

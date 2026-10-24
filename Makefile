COMPOSE     = docker compose -f infra/docker-compose.yml
COMPOSE_DEV = $(COMPOSE) -f infra/docker-compose.dev.yml

.PHONY: up up-dev down logs codegen codegen-check test lint fmt migrate env

env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - fill in secrets")

up: env
	$(COMPOSE) up -d --build

up-dev: env
	$(COMPOSE_DEV) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

codegen:
	bash packages/script-schema/codegen.sh

codegen-check:
	bash packages/script-schema/codegen.sh --check

test: codegen-check
	cd services/api && uv run pytest
	cd apps/render && pnpm test
	cd apps/web && pnpm test

lint:
	cd services/api && uv run ruff check . && uv run ruff format --check .
	cd apps/render && pnpm lint
	cd apps/web && pnpm lint

fmt:
	cd services/api && uv run ruff format . && uv run ruff check --fix .
	cd apps/render && pnpm fmt
	cd apps/web && pnpm fmt

# Requires Alembic to be set up in services/api (later step)
migrate:
	$(COMPOSE) exec api alembic upgrade head

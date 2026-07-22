# OSAIP developer entrypoints (spec §3.3). All targets run from the repo root.
COMPOSE := docker compose -f infra/compose/docker-compose.yml --project-name osaip

.PHONY: dev dev-down test test-py test-web lint lint-py lint-web e2e seed ci gen-api

## dev: boot the full dev stack (postgres+pgvector, seaweedfs, keycloak, api, worker, web)
dev:
	$(COMPOSE) up --build

dev-down:
	$(COMPOSE) down

## test: all unit/integration tests (Python + web)
test: test-py test-web

test-py:
	uv run pytest

test-web:
	pnpm run test

## lint: static checks (ruff, mypy --strict on packages/, eslint, tsc)
lint: lint-py lint-web

lint-py:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict packages/shared apps/api/osaip_api apps/worker/osaip_worker

lint-web:
	pnpm run lint
	pnpm run typecheck

## e2e: Playwright acceptance suite against the built web app (lands in slice 10)
e2e:
	@echo "e2e suite lands in slice 10 (Playwright against built output)"; exit 1

## seed: demo data (project, members, object_refs, notification) (lands in slice 10)
seed:
	@echo "seed lands in slice 10"; exit 1

## gen-api: export openapi.json and regenerate packages/api-client (lands in slice 6)
gen-api:
	@echo "gen-api lands in slice 6"; exit 1

## ci: the full local gate (mirrors .github/workflows/ci.yml)
ci: lint test

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
	uv run mypy --strict packages/shared packages/engine apps/api/osaip_api apps/worker/osaip_worker

lint-web:
	pnpm run lint
	pnpm run typecheck

## e2e: Playwright acceptance suite against built output (stops the dev web container)
e2e:
	$(COMPOSE) up -d --wait postgres keycloak api worker
	$(COMPOSE) stop web
	OSAIP_DATABASE_URL=postgresql+asyncpg://osaip:osaip@localhost:5433/osaip uv run python -m osaip_api.seed
	pnpm --filter @osaip/web e2e

## seed: demo data (project, members, object_refs, notification); idempotent
seed:
	uv run python -m osaip_api.seed

## gen-api: export openapi.json and regenerate packages/api-client (§3.2: no hand-written fetch)
gen-api:
	uv run python -m osaip_api.export_openapi > packages/api-client/openapi.json
	pnpm --filter @osaip/api-client generate
	pnpm --filter @osaip/api-client typecheck

## ci: the full local gate (mirrors .github/workflows/ci.yml)
ci: lint test
	$(MAKE) gen-api
	git diff --exit-code packages/api-client
	pnpm --filter @osaip/web build
	node scripts/check_bundle_size.mjs apps/web/dist
	uv run python scripts/check_licenses.py
	npx --yes @stoplight/spectral-cli@6.15.0 lint -r .spectral.yaml --fail-severity=error packages/api-client/openapi.json
	$(MAKE) e2e

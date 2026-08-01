# OSAIP developer entrypoints (spec §3.3). All targets run from the repo root.
COMPOSE := docker compose -f infra/compose/docker-compose.yml --project-name osaip
SPACY_NL_WHEEL := https://github.com/explosion/spacy-models/releases/download/nl_core_news_sm-3.8.0/nl_core_news_sm-3.8.0-py3-none-any.whl

.PHONY: dev dev-down test test-py test-web spacy-model lint lint-py lint-web e2e seed ci gen-api

## dev: boot the full dev stack (postgres+pgvector, seaweedfs, keycloak, api, worker, web)
dev:
	$(COMPOSE) up --build

dev-down:
	$(COMPOSE) down

## test: all unit/integration tests (Python + web)
test: test-py test-web

test-py: spacy-model
	uv run pytest

## spacy-model: install the pinned Dutch NER model (a BUILD step — OSAIP never
## downloads a model at runtime). `uv sync` prunes it because it is not in the lock,
## so this re-adds it; uv caches the wheel, so repeat runs are offline.
spacy-model:
	@uv run python -c "import spacy,sys; sys.exit(0 if spacy.util.is_package('nl_core_news_sm') else 1)" 2>/dev/null \
		|| uv pip install --quiet "$(SPACY_NL_WHEEL)"

test-web:
	pnpm run test

## lint: static checks (ruff, mypy --strict on packages/, eslint, tsc)
lint: lint-py lint-web

lint-py:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict packages/shared packages/engine packages/guardrails/osaip_guardrails apps/api/osaip_api apps/mesh/osaip_mesh apps/worker/osaip_worker
	# No eval/exec in the engine — the recipe expression language is AST-compiled (§10, ADR-0007).
	@! grep -rnE '\beval\(|\bexec\(' packages/engine/osaip_engine/ \
		|| (echo "FAIL: eval(/exec( found in engine" && exit 1)
	# §5b: no code path may call a provider SDK directly — only apps/mesh may import one.
	@! grep -rnE '^(from|import) (litellm|openai|anthropic)\b' \
		--include='*.py' apps packages --exclude-dir=mesh \
		|| (echo "FAIL: provider SDK imported outside apps/mesh (spec §5b)" && exit 1)

lint-web:
	pnpm run lint
	pnpm run typecheck

## e2e: Playwright acceptance suite against built output (stops the dev web container)
e2e:
	$(COMPOSE) up -d --wait postgres keycloak seaweedfs api mesh worker
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

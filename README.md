# OSAIP

**O**pen **S**ource **AI** **P**latform — a self-hostable, agent-first AI/data platform
in the spirit of Dataiku DSS: projects, connections, datasets, a visual Flow of recipes,
an LLM Mesh with guardrails and cost control, Knowledge Banks (RAG), a governed semantic
layer for natural-language analytics, a visual + code agent builder with MCP-native
tools, chat surfaces, evaluation, and governance — assembled from permissively licensed
open-source engines.

- Build authority: [PROJECT_SPEC.md](PROJECT_SPEC.md)
- Dutch public-sector compliance mapping: [COMPLIANCE_NL.md](COMPLIANCE_NL.md)
- Phase plans: [docs/plans/](docs/plans/)
- Decisions: [docs/adr/](docs/adr/)

## Status

Phases 0 (foundation & app shell) and 1 (connections & datasets) are complete; Phase 2 (Flow & recipes) is next.

## Quickstart (dev)

Prereqs: Docker + Compose, `uv`, Node 22, `pnpm`, `make`.

```bash
make dev      # boots postgres+pgvector, seaweedfs, keycloak (realm pre-imported), api, worker, web
```

Then open http://localhost:5173. Dev users (password `dev`): `admin@osaip.dev`,
`editor@osaip.dev`, `viewer@osaip.dev`.

Dev ports (chosen to avoid common defaults): web `5173`, api `8001`, Keycloak `8081`,
Postgres `5433`, SeaweedFS S3 `8333`.

```bash
make seed     # demo project (3 members), sales_orders search ref, welcome notification
make test     # Python + web unit/integration tests
make lint     # ruff, mypy --strict, eslint, tsc
make e2e      # Playwright acceptance suite (AC 1-7, axe, mobile, states)
make ci       # the full local gate incl. SBOM-adjacent license/bundle/OpenAPI checks
make gen-api  # regenerate packages/api-client from the API's OpenAPI
```

## Security

See [SECURITY.md](SECURITY.md) for the coordinated vulnerability disclosure policy.
The dev stack uses fixed dev-only credentials and plain HTTP — never expose it;
production guidance lives in `docs/deployment-checklist.md` (arrives with slice 10).

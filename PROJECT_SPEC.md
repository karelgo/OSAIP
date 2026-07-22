# OSAIP — an open-source, agent-first Dataiku-class platform
## Build spec & agent instructions for Claude Code · v4 (agentic core + semantic layer + unified UX)

You are building **OSAIP** (Open source AI platform): a self-hostable, web-based AI/data platform in
the spirit of Dataiku DSS with its agentic capabilities as the centerpiece — projects,
connections, datasets, a visual Flow of recipes, an LLM Mesh (secure gateway with guardrails
and cost control), Knowledge Banks (RAG), a **governed semantic layer for natural-language
analytics**, a visual + code Agent builder with MCP-native tools, chat surfaces (Answers,
Agent Hub), agent evaluation and governance, plus notebooks, a classic ML lab, scenarios, and
deployment — assembled from permissively licensed open-source engines with a custom
application layer on top.

Read this entire file before writing any code. Decisions marked **LOCKED** are fixed unless the
user explicitly changes them. When requirements are ambiguous, present 2–3 options with
trade-offs and ask; never silently invent product scope.

---

## 1. Product pillars (Dataiku → OSAIP)

### Data & ML foundation
| Dataiku concept | OSAIP equivalent |
|---|---|
| Project | Project (workspace with members, RBAC, storage prefix) |
| Connection | Connection (Postgres, S3, files; more later) |
| Dataset | Dataset (schema + location + params; Parquet on S3 or table ref) |
| Flow | Flow (DAG derived from recipes' inputs/outputs, rendered on a canvas) |
| Visual / code recipes | Prepare, Join, Group, Stack, Split, Sample + SQL & Python recipes |
| Scenarios | Scenarios (triggers + steps) |
| Metrics & checks | Dataset metrics & checks with gating |
| Notebooks / code envs | JupyterHub + per-project uv envs |
| Lab (visual ML) | ML Lab (train, AutoML, leaderboard, registry) |
| API Deployer | Deployments (models AND agents as APIs) |
| Dashboards | ECharts insights on dashboards |

### Agentic AI (THE FOCUS)
| Dataiku concept | OSAIP equivalent |
|---|---|
| LLM Mesh (secure gateway) | LLM Mesh service: provider connections, permissioning, audit of every call, caching, quotas |
| LLM connections (APIs + local HF models) | LLM connections via LiteLLM; local models via vLLM/Ollama containers |
| Guardrails (PII, toxicity, moderation) | Guardrail pipeline: Presidio PII redaction + judge-model moderation + custom rules |
| Cost Guard (monitoring + blocking) | Usage ledger + budgets/quotas per project/user/agent, warn/block at gateway |
| Prompt Studio + Prompt Recipes | Prompt Studio (compare prompts × models) + prompt registry + Prompt recipe for batch runs |
| LLM recipes (classify, summarize) | LLM recipes: prompt, classify, extract, summarize on dataset columns |
| Knowledge Banks + embedding recipes | Knowledge Banks: Docling parse → chunk → embed recipes into pgvector |
| **Semantic Models** (entities, attributes, metrics, glossary, golden queries) | **Semantic models: entities/attributes/relationships/metrics over datasets, compiled via Ibis; glossary + golden queries; NL analytics grounding** |
| **Semantic Model Query tool / SQL QA tool** | **`semantic_query` managed tool (governed, preferred) + read-only `sql_query` fallback** |
| Answers (RAG chat UI) | Answers: chat over KBs/datasets + **data mode** (NL → governed semantic query) with citations, history, feedback |
| Agents (visual + code) | Agents: visual graph builder (compiles to LangGraph) + code agents |
| Tools management | Tools: managed built-ins + external MCP servers; per-tool human approval |
| Agent-as-LLM in the Mesh | Every approved agent callable through the mesh + OpenAI-compatible endpoint |
| Trace Explorer | Native Trace Explorer (OTel GenAI spans: prompts, tool calls, plans, costs) |
| Agent Connect / Agent Hub | Agent Hub: agent library, my-agents from templates, multi-agent routing chat |
| Quality Guard (golden sets, LLM-judge) | Evaluations: eval sets, graders (heuristic + LLM-as-judge + Ragas/DeepEval), gates |
| Agent governance (sign-off, registry) | Agent lifecycle: draft → review → approved → deployed, with audit |
| AI assistants / Cobuild | Studio Copilot: platform's own MCP server + assistant (NL→prep steps, NL→semantic query, explain flow) |

## 2. Non-goals for v1

- Distributed compute (Spark/Trino) — designed for via the engine interface, built in Phase 13.
- Streaming / real-time pipelines.
- LLM fine-tuning (Phase 13; design the mesh so fine-tuned local models just register).
- Multimodal *generation* (image/audio out). Document + image *inputs* to agents are in scope.
- Auto-generated slide "Stories"; full enterprise data catalog; column-level ACLs;
  plugin marketplace (define plugin/tool interfaces cleanly; no store).

## 3. Locked architecture

### 3.1 License policy (LOCKED)
- In-process dependencies: Apache-2.0 / MIT / BSD / PSF / PostgreSQL licenses only.
- AGPL/GPL or source-available (ELv2, BUSL, FSL) software may only run as an OPTIONAL
  out-of-process service, off by default, spoken to over a network API.
- Never use MinIO (archived/unmaintained). Dev object store = SeaweedFS; production = any
  S3-compatible endpoint. All storage access via one internal storage interface.
- Before proposing ANY new dependency, check its license against this policy and record it.

### 3.2 Stack (LOCKED)

**Backend**: Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, `uv`.
**Metadata DB**: PostgreSQL 16 **with pgvector** (single DB for app metadata, usage ledger,
traces, vectors, and semantic resolution indexes in v1).
**Jobs**: Postgres-backed queue (`FOR UPDATE SKIP LOCKED`) + worker processes; APScheduler for
cron. NOT Airflow/Dagster in-core; external executors later behind `JobExecutor`.
**Object storage**: S3 API only; datasets at
`s3://<bucket>/projects/<key>/datasets/<name>/v<N>/part-*.parquet`; documents under
`.../documents/`; traces/logs under `.../artifacts/`.
**Compute v1**: DuckDB embedded (preview, profiling, recipe execution over Parquet/S3 + attached DBs).
**Recipe abstraction**: Ibis. Visual recipe JSON → Ibis → engine (DuckDB now; Trino/Spark later).
**Python sandbox**: per-project uv envs; subprocess with CPU/mem/time limits, no network by
default; all data IO via the SDK broker (no ambient credentials).

**LLM Mesh (LOCKED picks)**
- Gateway: **LiteLLM** (MIT) embedded as the `mesh` service. Every model call in the platform —
  recipes, agents, chat, evals, semantic planner, copilot — goes through it. Provider keys via
  secret refs only.
- Local models: optional **vLLM** (Apache-2.0) and **Ollama** (MIT) containers registered as
  mesh connections (the "locally hosted models" analog).
- Guardrails: pipeline stages `pre` (input) and `post` (output): **Presidio** (MIT) PII
  detect/redact, judge-model moderation via the mesh, regex/denylist rules, max-token and
  schema validators. Policies attach to LLM connections and to agents. NeMo Guardrails
  (Apache-2.0) may be added later behind the same stage interface — ADR first.
- Caching: response cache keyed on (model, normalized messages, params) in Postgres/Redis.
- Cost: usage ledger rows for every call (tokens, computed cost, latency, cache hit); quotas
  (project/user/agent × period) enforced at the gateway: warn → block.
- Audit: every prompt/response persisted (with PII-redacted variant) unless the connection
  opts out; linked to trace spans.

**RAG / Knowledge Banks (LOCKED picks)**
- Parsing: **Docling** (MIT) for PDF/DOCX/PPTX/HTML → structured text with layout.
- Chunking: built-in strategies (by heading/tokens/semantic) as recipe params.
- Embeddings: any embedding model via the mesh.
- Vector store: **pgvector** default (one table per KB, HNSW index). `VectorStore` interface so
  Qdrant/LanceDB (Apache-2.0) can slot in later — ADR first.
- Retrieval: hybrid (vector + Postgres FTS) with reranking via a mesh model (optional).

**Semantic layer (LOCKED picks)**
- **Native semantic models — no third-party semantic engine in-process.** A model consists of:
  entities bound to datasets; attributes (columns) with descriptions and optional categorical
  sample-value indexing; relationships (join graph); metrics (aggregations, incl. cross-entity
  via the join graph); named filters; free-text instructions for the planner.
- Business glossary: terms with descriptions + synonyms, entered manually or extracted from
  documents via Docling (reuses packages/rag); terms link to entities/attributes/metrics/filters.
- Golden queries: curated NL question → semantic-plan pairs; used as few-shot context for the
  planner AND replayed as CI regression tests.
- Compiler: a semantic query is a **validated JSON plan** {metrics, dimensions, filters,
  time grain, order, limit} — the LLM never writes SQL — compiled via Ibis to the underlying
  datasets' engine (DuckDB now; pushdown engines later). Lives in `packages/semantics`,
  reusing `packages/engine`.
- Indexing: a per-model resolution index (pgvector) of attribute names, metric names, glossary
  terms, and sampled categorical values, embedded via the mesh — so "turnover" resolves to the
  `revenue` metric and "NL" to `country = 'Netherlands'`.
- Query modes: `simple` (one-shot plan) and `agentic` (iterative refine with tool feedback),
  configurable per tool/app.
- Security: semantic queries execute under the invoking user's dataset permissions —
  permission passthrough, never a service account.
- Interop: model format documented and aligned with **Open Semantic Interchange (OSI)** where
  practical; Phase 13 adds OSI/MetricFlow (Apache-2.0) import-export and an optional **Cube
  Core** sidecar to serve external BI tools over SQL/REST — ADR first. MetricFlow and Cube are
  NOT embedded in-process in v1.

**Agents (LOCKED picks)**
- Runtime: **LangGraph** (MIT). Visual agents = graph JSON (llm, tool, retrieval, router,
  condition, human-approval nodes) compiled to LangGraph; code agents = Python via SDK
  (`OSAIP.agent`) with LangGraph + **PydanticAI** (MIT) helpers; any framework allowed if
  it implements the AgentRunner protocol.
- Tools: **MCP-native**. Built-in managed tools: **semantic_query** (governed NL analytics —
  the PREFERRED analytics tool), dataset_query (safe SQL over datasets), sql_query (against a
  connection, read-only default), kb_retrieval, model_score (registered ML models),
  http_request (allowlisted), python_function (sandboxed), web_search (pluggable). External
  tools = remote MCP servers registered per project. The platform ALSO exposes its own MCP
  server (projects/datasets/recipes/jobs/semantic models as tools) — this powers Studio
  Copilot and lets external agents (e.g. Claude) drive the platform.
- Human-in-the-loop: any tool can be marked `requires_approval`; the run pauses and surfaces an
  approval request (Dataiku's toolValidationRequests analog).
- Agent-as-LLM: approved agents are callable through the mesh like any model, and every
  deployed agent gets an OpenAI-compatible `/v1/chat/completions` endpoint.
- Tracing: OTel GenAI semantic conventions; spans stored in Postgres; native Trace Explorer UI
  (tree view: prompts, tool calls, retrievals, semantic plans, costs, latencies). Optional
  exporters (Langfuse MIT-core, OTLP) later — ADR first.
- Chat frontend: **Vercel AI SDK** (Apache-2.0) streaming + **assistant-ui** (MIT) components.

**Evaluation & monitoring (LOCKED picks)**
- Eval sets are ordinary datasets in the Flow (question, reference, metadata); golden queries
  are the semantic layer's eval sets.
- Graders: heuristic (exact/regex/contains/JSON-schema), **Ragas** + **DeepEval**
  (Apache-2.0) metrics, LLM-as-judge via the mesh with rubric prompts from the prompt registry.
- Production monitoring: usage/cost/latency/feedback dashboards native; **Evidently**
  (Apache-2.0) LLM presets for drift on inputs/outputs; alerts via scenarios.

**Classic ML (unchanged)**: scikit-learn, XGBoost, LightGBM; FLAML AutoML; MLflow tracking +
registry; SHAP; Evidently drift; model serving as per-deployment FastAPI containers.
**Quality**: Pandera in-recipe; dataset metrics & checks via DuckDB.
**Ingestion**: dlt (Apache-2.0) for API/SaaS sources; native file/S3/SQL paths.
**Frontend**: React 18 + TS strict + Vite + pnpm; `@xyflow/react` + @dagrejs/dagre (Flow AND agent
canvases share one graph-canvas package); TanStack Router + Query/Table; Zustand;
react-hook-form + zod; cmdk; shadcn/Radix components; Monaco; ECharts; Tailwind. Full IA,
design system, interaction patterns, and budgets: **§6**.
**AuthN/Z**: OIDC (Keycloak dev container, generic OIDC in code); single `permissions` module.
**API client**: generated from OpenAPI; never hand-write API types.
**Packaging**: docker compose (dev + single-node prod); Helm in Phase 13.

### 3.3 Repository layout (monorepo)

```
OSAIP/
  apps/api/           # FastAPI app: routers/, services/, models/, alembic/
  apps/worker/        # job runner, schedulers, recipe + eval + indexing executors
  apps/mesh/          # LLM gateway service (LiteLLM embedded, guardrails, ledger, cache)
  apps/web/           # React app
  packages/engine/    # recipe schemas, Ibis compiler, engine adapters, expression parser
  packages/semantics/ # semantic model schema, metric/plan→Ibis compiler, NL planner, resolution index
  packages/agents/    # agent graph schema, LangGraph compiler, AgentRunner, tool broker, MCP client+server
  packages/rag/       # docling parsing, chunkers, VectorStore interface, retrievers
  packages/evals/     # graders, judge harness, eval + golden-query runners
  packages/sdk/       # OSAIP.dataset(...), .llm(...), .agent(...), .semantic(...)
  packages/canvas/    # shared xyflow graph-canvas components (Flow + agent builder)
  packages/ui/        # design tokens, themed components (shadcn/Radix), Storybook
  packages/api-client/# OpenAPI-generated TS client + typed TanStack Query hooks
  packages/shared/    # shared pydantic models & constants
  infra/compose/      # postgres(+pgvector), seaweedfs, keycloak, mesh, mlflow, jupyterhub, ollama(optional)
  docs/adr/  docs/plans/  Makefile (dev|test|e2e|lint|seed)
```

## 4. Domain model (Postgres)

Foundation (unchanged from v1): `users`, `groups`, `project_members(role)`, `projects`,
`connections` (secrets encrypted/ref'd), `datasets`, `recipes` (Flow derived from
inputs/outputs; enforce DAG + single producer), `jobs`, `job_steps`, `scenarios`,
`scenario_runs`, `metrics`, `checks`, `experiments`, `model_versions`, `deployments`,
`audit_log`. UUIDv7 PKs, timestamps everywhere.

Agentic additions:
- `llm_connections(scope global|project, provider, base_config, allowed_models[], secret_ref,
  guardrail_policy_id, cache_ttl, audit_mode)`
- `llm_calls(ts, project_id, user_id, agent_id?, session_id?, trace_id, model, purpose,
  tokens_in, tokens_out, cost, latency_ms, cache_hit, guardrail_events_json, status)` — the ledger
- `quotas(scope_type project|user|agent|connection, scope_id, period, limit_cost, limit_calls,
  action warn|block)`
- `guardrail_policies(name, stages_json)` and `guardrail_events(call_id, stage, rule, action, details)`
- `prompts(project_id, name, version, template, variables_json, model_defaults_json, tags)` — registry
- `knowledge_banks(project_id, name, embedding_model, chunking_config_json, vector_ref,
  retrieval_config_json, status, last_sync)`
  + `kb_sources(kb_id, kind dataset|documents, ref, filter)` + one pgvector chunk table per KB
- **Semantic layer**:
  `semantic_models(project_id, name, status draft|certified, owner)` +
  `semantic_model_versions(sm_id, version, definition_json, changelog)` (definition holds
  entities, attributes, relationships, metrics, filters, instructions);
  `glossary_terms(project_id, name, description, synonyms[], links_json)`;
  `golden_queries(sm_id, name, nl_question, plan_json, certified)`;
  one pgvector resolution-index table per model; `sm_index_runs(sm_id, status, stats, ts)`
- `tools(scope, name, type, config_json, requires_approval, scopes[], enabled)`
- `agents(project_id, name, kind visual|code, status draft|review|approved|archived)`
  + `agent_versions(agent_id, version, definition_json|code_ref, model, tool_ids[], kb_ids[],
    sm_ids[], guardrail_policy_id, eval_gate_id?, changelog)`
- `agent_deployments(agent_version_id, slug, token_hash, status, quota_id)`
- `chat_apps(project_id, kind answers|hub, config_json)` , `chat_sessions(app_id|deployment_id,
  user_id, title)` , `chat_messages(session_id, role, content_json, trace_id, feedback int?,
  feedback_text?)`
- `traces(trace_id, root_kind agent|recipe|chat|eval|semantic, project_id, agent_version_id?,
  started, duration_ms, total_cost, span_count)` + `spans(trace_id, span_id, parent_id, kind
  llm|tool|retrieval|guardrail|agent|plan, name, input_json, output_json, tokens, cost, t0, t1, status)`
- `eval_sets(project_id, dataset_id, mapping_json)` , `graders(name, kind heuristic|metric|judge,
  config_json)` , `eval_runs(target_kind agent_version|prompt_version|semantic_model_version,
  target_id, eval_set_id, grader_ids[], status, scores_json, verdict pass|fail, report_ref)`
- `approvals(kind tool_call|agent_promotion|sm_certification, ref, requested_by, payload_json,
  status, decided_by, ts)`
- **App shell**: `object_refs(kind, id, project_id, name, description, updated_at)` search
  registry; `notifications(user_id, kind, ref, severity, read_at)`;
  `user_prefs(user_id, theme, density, pinned_json)`

## 5. Reference execution paths (keep these true at all times)

### 5a. How a recipe runs (unchanged)
UI saves recipe JSON → Build resolves stale upstream subgraph → job + steps → worker compiles
payload → Ibis bound to inputs (DuckDB over Parquet/S3 or attached DBs) → execute → atomic
Parquet write `v<N>` → update schema/rows/lineage/metrics → logs to object storage, SSE to UI.

### 5b. How ANY model call runs (the Mesh path)
caller (recipe | agent | chat | eval | semantic planner | copilot) → `apps/mesh`:
authz (project + connection permission) → quota check (block/warn) → cache lookup →
guardrails `pre` (PII redact, rules) → LiteLLM → provider/local model →
guardrails `post` (moderation, schema) → ledger row + audit + span → response (streamed).
No code path may call a provider SDK directly. Ever.

### 5c. How an agent run works
entrypoint (test console | chat | deployment endpoint | mesh agent-as-LLM | scenario step) →
load approved agent_version → AgentRunner (LangGraph) with a **tool broker**:
every tool call re-checks project permissions of the *invoking user/service*, read-only by
default, `requires_approval` tools pause the run into `approvals` and resume on decision →
all LLM calls inside go through 5b → root trace + span tree persisted with cost rollup →
response streamed; feedback attaches to the message + trace.

### 5d. Prompt-injection posture (LOCKED)
Retrieved chunks, documents, tool outputs, and web content are DATA, never instructions:
system prompts assembled server-side from the registry; untrusted content is delimited and
tagged; side-effectful tools default to `requires_approval`; http_request is allowlisted;
agents get least-privilege tool sets; secrets never enter prompts; injection test cases ship
in the default eval sets.

### 5e. How a governed NL analytics question runs (the semantic path)
question (Answers data mode | `semantic_query` tool | playground) →
resolve terms against the model's resolution index (embeddings via 5b) →
planner LLM drafts a **validated JSON plan** {metrics, dimensions, filters, grain, limit}
using golden queries as few-shots — **the LLM never writes SQL** →
plan validated against the model schema → compiled via Ibis → executed on the datasets'
engine under the invoking user's permissions → result table + chart hint + the plan echoed
for auditability → span records plan + row counts.
Low planner confidence → ask a clarifying question instead of guessing.
Users can save results as insights or promote the question→plan pair to a golden query.
Modes: `simple` (one-shot) and `agentic` (iterative refine), per tool/app setting.

## 6. Application shell, frontend & UX architecture (LOCKED)

Dataiku's weakness is accretion: fifteen modules with fifteen UI dialects. OSAIP's
differentiator is coherence — one shell, one canvas grammar, one run model, one trace
affordance. Every module plugs into the same five surfaces: rail, canvas/list, inspector,
dock, drawer.

### 6.1 Personas & modes
- **Studio** (`/p/<key>/…`) — builders and analysts; full IA below; role-aware (viewers get
  read-only affordances, never hidden-broken buttons).
- **Hub** (`/hub`) — consumers; chat-first portal over approved agents, Answers apps, and
  shared dashboards; zero studio chrome; mobile-friendly. A consumer never needs to learn
  the studio.

### 6.2 Studio information architecture
Top bar: project switcher (recents + search) · ⌘K omnibar · run bell · approvals inbox ·
Copilot toggle · user menu.
Left rail (grouped, collapsible to icons):
```
Flow                      ← project home
Data         Datasets · Notebooks
Grounding    Knowledge · Semantic
Agents       Agents · Prompts & Tools · Evals · Traces
Chat         Answers apps · Hub
ML Lab
Automation   Scenarios · Jobs
Deploy       Deployments · Monitoring
Dashboards
Settings
```
Everything is deep-linkable; the URL carries selection, filters, and open panels.

### 6.3 Signature interaction patterns (the UX contract)
1. **One canvas grammar** — Flow and agent graphs share node anatomy: domain color
   (data / AI / ML / IO), status ring (queued / running / ok / failed / stale), badges
   (certified, requires-approval). Learn it once, read every graph in the product.
2. **Inspector, not modals** — selecting anything opens the right-side inspector with the
   same tab order everywhere: Configure · Preview · Runs · Lineage/Traces · Docs. Modals are
   reserved for destructive confirmation.
3. **Preview-first** — every recipe/semantic/config edit live-previews on a DuckDB sample
   (<300 ms target) before anything is built; agents preview via the test console.
4. **One run model** — every execution (build, KB sync, index, eval, agent run) is a Job with
   the same bottom run-drawer: step timeline + live logs over SSE; canvas nodes animate the
   same states; toasts deep-link into the drawer.
5. **⌘K omnibar** — hybrid search over every object plus actions ("build orders_clean",
   "new agent from template", "open trace …"); unresolved input falls through to Copilot.
6. **Copilot dock, diff-first** — the copilot lives in a right dock, sees the current
   selection, and proposes changes as reviewable diff-cards (prepare steps, semantic plan,
   agent-graph patch) with an explicit Apply. It never mutates anything silently.
7. **Trace-everywhere** — any AI-produced value (chat answer, classified cell, semantic
   result, copilot suggestion) carries a quiet "why?" affordance opening the trace in the dock.
8. **Approvals inbox** — pending tool approvals, agent promotions, and model certifications in
   one queue; each card shows who/what/arguments/risk with approve/deny + comment and
   deep-links into the paused trace.
9. **Empty states are starting points** — every empty list offers 2–3 templates and a seed
   action; new projects get an onboarding checklist (connect → dataset → build → agent).
10. **Progressive disclosure** — defaults first, Advanced behind an accordion; consumer
    surfaces hide builder vocabulary entirely.

### 6.4 Design system & identity (`packages/ui`)
- Tokens as CSS variables: graphite/off-white neutral scale, ONE accent, and a semantic
  status palette (shared by jobs, evals, guardrails) kept visually distinct from the accent;
  4 px spacing grid; radius + elevation scales; light and dark derived from the same tokens;
  comfortable/compact density.
- Identity: deliberately NOT the template looks (cream + terracotta serif, black + acid
  green, hairline broadsheet). Type: **IBM Plex Sans** for UI and **IBM Plex Mono** for
  code/data (both OFL), tabular numerals everywhere data appears. The one signature element
  is **the living Flow**: during any run, status pulses travel along graph edges — everything
  else stays quiet and disciplined.
- Components: shadcn/ui patterns over Radix primitives (MIT) restyled with our tokens; icons
  lucide (ISC); ECharts theme generated from the tokens; motion 120–200 ms with
  `prefers-reduced-motion` respected.
- Copy voice (enforced in review): sentence case; active verbs; controls say what they do
  ("Save changes", not "Submit") and keep their name through the flow; name things by the
  user's mental model, never by internals; errors state what happened and how to fix it;
  empty states invite action.
- Accessibility: WCAG 2.1 AA; complete keyboard support including canvas navigation (arrows
  between nodes, Enter opens inspector). Storybook is the component workshop; Playwright
  screenshot diffs in CI guard visual regressions.

### 6.5 Frontend architecture (`apps/web`)
- **TanStack Router** (type-safe routes, MIT) + **TanStack Query**; **Zustand** (MIT) for
  local UI state; **react-hook-form + zod** (MIT) for forms; **cmdk** (MIT) for the omnibar.
- Feature-sliced layout: `app/` (routes, providers) · `features/<module>/` · `entities/`
  (cross-module pickers: DatasetPicker, ModelPicker, TracePeek) · `shared/`.
- `packages/api-client`: generated from OpenAPI including typed TanStack Query hooks;
  hand-written fetch code is forbidden.
- Route-level code splitting per module; virtualized tables; skeletons over spinners;
  optimistic mutations with idempotency keys; dagre layout runs in a web worker.
- Budgets (CI-checked where practical): initial route JS < 300 KB gz; p95 interaction
  < 100 ms; 1k-row preview < 300 ms; a 500-node canvas stays smooth.

### 6.6 BFF & realtime (additions to `apps/api`)
- **`GET /events`** — one multiplexed SSE channel (topics: jobs, traces, chat, approvals,
  quotas, notifications) backed by Postgres LISTEN/NOTIFY; a single reconnecting client
  drives TanStack Query cache invalidation.
- **`GET /search`** — hybrid FTS + pgvector over the `object_refs` registry (every named
  object: datasets, recipes, metrics, agents, prompts, KBs, dashboards); powers ⌘K.
- **Notifications/inbox** — approvals, failures, eval regressions, budget warnings.
- **View-model endpoints** for heavy screens (Flow graph + statuses in one GET; project
  overview) returning server-computed capability flags — the UI never guesses permissions.
- **API conventions**: cursor pagination; ETags on heavy GETs; problem+json errors carrying a
  user-facing hint and a docs link; idempotency keys accepted on all POSTs.

### 6.7 UX definition-of-done (every screen, every phase)
Loading skeleton · designed empty state with a CTA · error state with hint + retry · complete
keyboard path · dark mode · deep-linkable · run/trace affordance wherever jobs or AI are
involved · Hub-facing surfaces usable on mobile.

## 7. Build phases & acceptance criteria

One phase at a time. DONE = acceptance tests green in CI, `make dev` boots clean, demo seed
works, docs + CHANGELOG updated, and every new screen passes the §6.7 UX checklist.

### Phase 0 — Foundation & app shell
Monorepo scaffold; compose (postgres+pgvector, seaweedfs, keycloak, api, worker, web); OIDC
login; projects CRUD + RBAC; audit log; **design system v1** (tokens, dark mode, ~12 core
components in packages/ui + Storybook); **app shell** (left-rail IA, top bar, project
switcher); **⌘K omnibar** (object nav + action registry skeleton); **SSE event bus** +
notifications inbox skeleton; CI (ruff, mypy, pytest, vitest, Playwright smoke + visual smoke).
**AC**: login via Keycloak; create project; viewer role cannot modify; mutations audited; the
shell is fully keyboard-navigable in dark mode; ⌘K jumps to a seeded dataset; a test event
arrives as a toast + inbox item over SSE.

### Phase 1 — Connections & datasets
Connections: postgres, s3, file upload (csv/parquet/xlsx), duckdb-file. Dataset registration,
schema inference, 1k-row preview + column profiling via DuckDB; dataset page (schema/sample/profile).
**AC**: CSV upload → typed schema + profile; Postgres table registered → preview; bad creds
fail cleanly without leaking.

### Phase 2 — Flow & recipes v1
Flow canvas (packages/canvas); recipe framework; visual recipes: prepare (rename, cast,
filter, formula via safe AST parser, fill nulls, dedupe), join, group, stack, split, sample;
code recipes: SQL, Python (sandboxed, SDK IO). Build with stale-only rebuilds; job page with
live logs; lineage panel. This phase establishes the canonical inspector and run-drawer
patterns (§6.3) that every later module reuses.
**AC (e2e)**: CSV → prepare → join(Postgres) → group builds; mid-flow edit rebuilds only stale.

### Phase 3 — LLM Mesh  ★ agentic arc begins
`apps/mesh` service: LLM connections (OpenAI-compatible, Anthropic, plus one local via
Ollama), model allowlists + per-project permissioning; usage ledger + cost computation; quotas
with warn/block; response cache; guardrail pipeline v1 (Presidio PII redact, denylist,
judge-model moderation, max-tokens); full call audit; **LLM recipes** in the Flow: prompt
(free template on columns), classify, extract (JSON-schema), summarize; **Prompt Studio**:
prompt registry + side-by-side runs across prompts × models on sample rows, promote → Prompt
recipe.
**AC**: classify recipe runs on a dataset via two different connections with identical code
path; ledger shows tokens+cost per call; a low quota blocks with a clear error; PII in a test
prompt is redacted in the stored audit; Prompt Studio comparison table renders and promotes.

### Phase 4 — Knowledge Banks & RAG + Answers
Document sources (upload folder / S3 prefix / dataset column); Docling parse recipe; chunk +
embed recipes → KB in pgvector (HNSW); retrieval test bench (query → chunks + scores); hybrid
retrieval option; **Answers** chat app per project: pick KBs/datasets + model + guardrails →
streaming chat with citations to chunks/documents, history, thumbs feedback; scheduled KB
sync via a job (full scenario UI arrives Phase 8).
**AC**: 3 PDFs → KB; Answers cites the correct source page for a known fact; adding a doc +
resync makes it retrievable; feedback persists and links to the trace.

### Phase 5 — Semantic models & governed NL analytics  ★ NEW
Semantic model editor: entities from Flow datasets, attributes with descriptions + optional
sample-value indexing, relationships (join graph), metrics (incl. cross-entity), named
filters, planner instructions; **glossary** (manual entry + Docling extraction from business
documents, linked to model objects); **indexing job** (embed names/terms/sample values into
the resolution index via the mesh); plan compiler + `POST /semantic/query`; **playground**
(ask → see resolved terms + JSON plan → result → refine model); **golden queries** (save from
playground; replayed in CI via packages/evals); `semantic_query` registered as a managed
tool; **Answers data mode** (NL → plan → table + auto-chart, executed plan visible on
demand); permission passthrough enforced end-to-end.
**AC**: model over the seed sales schema; "monthly revenue by region for last year" in
Answers data mode matches a hand-written SQL check exactly; "turnover" resolves to the
`revenue` metric via a glossary synonym; the trace shows the JSON plan and no model-written
SQL anywhere; golden-query replay runs in CI and fails on a deliberately broken metric
definition; a user without dataset access gets a permission error, not data.

### Phase 6 — Agents & Tools + Trace Explorer
Agent object + versioning; **visual agent builder** on the shared canvas (nodes: llm, tool,
retrieval, router, condition, human-approval) compiling to LangGraph; **code agents** via SDK;
**tools framework**: managed built-ins (semantic_query from Phase 5, dataset_query, sql_query
read-only, kb_retrieval, model_score, http_request allowlisted, python_function sandboxed) +
register external MCP servers; platform's own MCP server v1 (list/query datasets, run recipe,
read job status, semantic_query); `requires_approval` flow; agent test console (chat + live
trace); **Trace Explorer** (tree of spans with prompts, tool IO, semantic plans, costs,
latencies; filter by agent/session/status).
**AC (e2e)**: visual agent with kb_retrieval + semantic_query answers a question needing
both — the trace shows the tool calls and the JSON plan; a write-marked tool pauses for
approval and resumes; the same agent invoked through the mesh as a model returns identically;
Studio's MCP server lets an external MCP client list datasets and run a semantic query.

### Phase 7 — Agent Hub, deployment, Quality Guard, governance
**Deployment**: deploy approved agent version → versioned endpoint `/api/agents/<slug>` +
OpenAI-compatible chat route, per-deployment tokens + quota; **Agent Hub**: agent library
(enterprise / my agents / shared), Quick-Agent creation from templates (name, instructions,
pick tools/KBs/semantic models), multi-agent hub chat with router agent (query → best agent,
visible in trace); **consumer portal at `/hub`** (chat-first, zero studio chrome,
mobile-friendly); **Evaluations**: eval sets from datasets, graders (heuristic,
Ragas/DeepEval, LLM-judge with rubric prompts), eval runs with reports; **gates**: promotion
to `approved` requires a passing eval run + a human approval record (same flow certifies
semantic models); **monitoring**: per-agent dashboards (volume, cost, latency, feedback rate,
guardrail events), Evidently drift on question/answer distributions, alert hooks; **Studio
Copilot** shipped as a default enterprise agent over the platform MCP server (NL→prepare
steps proposal, NL→semantic-first analytics with SQL-recipe fallback, explain-this-flow).
**AC**: Quick Agent from template in <2 min; failing eval blocks promotion, passing enables
it; hub routes two distinct questions to two different agents (trace proves it); deployment
endpoint enforces token + quota; a consumer-role account lands in `/hub` and never sees
studio chrome; copilot answers an analytics question via semantic_query and
generates a prepare recipe from NL that the user applies.

### Phase 8 — Scenarios, metrics & checks
Triggers (cron, manual, dataset-updated); steps: build datasets, run checks, **sync KB**,
**reindex semantic model**, **run eval**, run Python, notify (webhook/email). Metrics & checks
UI with pass/warn/fail gating.
**AC**: nightly scenario rebuilds the chain, syncs a KB, reindexes the semantic model, runs an
agent eval, and a failing check or eval aborts + notifies.

### Phase 9 — Notebooks & code envs
Per-project uv envs UI; JupyterHub (Docker spawner, SSO); SDK preinstalled incl.
`OSAIP.llm`, `OSAIP.agent`, `OSAIP.semantic`; notebook → Python recipe / code
agent conversion.
**AC**: notebook reads a dataset, calls the mesh, runs a semantic query, writes a dataset;
convert to recipe appears in Flow.

### Phase 10 — ML Lab
Train UI (target, task auto-detect, feature handling), sklearn/XGB/LGBM + FLAML AutoML budget;
MLflow tracking; leaderboard, curves, importance + SHAP; registry promotion.
**AC**: two-click AutoML on seed data → leaderboard → best model registered.

### Phase 11 — Model deployment & monitoring (classic)
Batch score recipe; real-time scoring containers with tokens; Evidently drift vs training
reference. Registered models auto-available as the `model_score` agent tool.
**AC**: deploy model, curl predict (401 without token), drift report renders, an agent calls it.

### Phase 12 — Dashboards, insights, sharing
ECharts chart builder → insights → dashboards; **insights can be created directly from
semantic queries so dashboard KPIs share the governed metric definitions**; viewer read-only
sharing; project export/import.
**AC**: dashboard from Flow outputs incl. one semantic-query insight; viewer read-only;
export/import round-trips.

### Phase 13 — Scale-out & ecosystem (ADR each)
Trino/Spark via Ibis; Iceberg + REST catalog (Lakekeeper); external executor (Kestra/Dagster);
dlt connector hub UI; OpenLineage emission; Superset embed; Streamlit apps; Helm; fine-tuning
(HF TRL/Axolotl) registering into the mesh; alternate vector stores; Langfuse/OTLP trace
export; **semantic interop: OSI + MetricFlow (Apache-2.0) import/export, optional Cube Core
sidecar exposing models to external BI over SQL/REST**.

## 8. Engineering conventions
- Python: ruff, `mypy --strict` on packages/, pytest + testcontainers; httpx route tests.
- TS: strict, no `any`; vitest; Playwright covers exactly the AC e2e flows.
- DB: Alembic only; parameterized queries everywhere (including dataset_query/sql_query tools —
  these also pass through a SQL validator enforcing read-only + table allowlists).
- Security: secrets via env/refs, encrypted at rest; sandbox gets no ambient creds; SSRF-guard
  all user URLs incl. http_request tool; hash all tokens; §5d prompt-injection rules are
  release-blocking; permission passthrough (§5e) is release-blocking; upload validation + limits.
- Every non-trivial choice → 1-page ADR. Conventional commits; never commit secrets or .env.

## 9. How you (the agent) must work
1. Session start: read this spec, `docs/plans/`, latest ADRs.
2. Per phase: FIRST write `docs/plans/phase-N.md` (endpoints, schemas, components, test list,
   risks; <150 lines) and get approval before implementing.
3. Vertical slices (API + UI + tests), `make test` stays green, commit per slice.
4. Phase end: full e2e, refresh demo seed, docs + CHANGELOG, summarize, stop.
5. No dependency outside §3.2 without §3.1 license check + ADR + explicit approval.
6. If a LOCKED choice proves unworkable, stop and present alternatives — never swap silently.
7. Boring, contributable patterns over cleverness.

## 10. Known risks & fallbacks
- **Prompt injection is the top product risk**: §5d is mandatory; red-team eval set ships in seed.
- **NL-to-data correctness**: never execute model-generated SQL; plans are schema-validated;
  golden queries are the regression net; low confidence → clarifying question, never a guess;
  every answer exposes its plan for audit.
- **Cost blowouts**: quotas are mandatory on every connection from Phase 3; default budgets in seed.
- **Python/tool sandboxing**: v1 subprocess + limits + no network; executor interface allows
  container-per-execution (nsjail/gVisor) later; document the multi-tenant caveat.
- **LiteLLM surface area**: pin the version; wrap behind `apps/mesh`'s own API; only enable
  the features listed in §3.2.
- **pgvector scale**: fine for v1; VectorStore interface + Phase 13 alternates if it outgrows.
- **LangGraph churn**: pin; compile from OUR graph JSON so the runtime can be replaced.
- **Semantic-model sprawl**: certification workflow + owners; uncertified models are clearly
  flagged in Answers/agents.
- **Expression language**: parsed AST with an allowlist — never eval/exec.
- **Keycloak dev friction**: pre-imported realm; `make dev` = zero clicks.
- **Design drift across 13 phases**: packages/ui tokens + Storybook + the §6.7 checklist are
  the contract; CI screenshot diffs catch regressions.
- **Scope creep**: Dataiku took 15 years; anything not in §7 = new ADR + user decision.

## 11. Glossary (Dataiku → this project)
Flow→Flow · Recipe→Recipe · Dataset→Dataset · Scenario→Scenario · Lab→ML Lab ·
LLM Mesh→LLM Mesh · Knowledge Bank→Knowledge Bank · Prompt Studio→Prompt Studio ·
Semantic Model→Semantic model · Golden Queries→Golden queries · Answers→Answers ·
Agent Connect/Agent Hub→Agent Hub · Guard Services→Quotas/Guardrails/Evaluations ·
Trace Explorer→Trace Explorer · API Deployer→Deployments · Code env→Code env

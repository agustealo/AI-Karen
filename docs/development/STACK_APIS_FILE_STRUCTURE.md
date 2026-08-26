# Stack, APIs, and File Structure

## 1. Technology policy

KAREN is architecture-first, not dependency-first. A framework may implement a boundary, but must not replace KAREN's canonical contracts or create a second authority.

## 2. Primary languages

### Python

Primary backend, AI/runtime, orchestration, memory, providers, extensions, security, and observability language.

Use modern type hints on public boundaries and important runtime state. Async I/O uses `asyncio`/ASGI semantics.

### TypeScript / JavaScript

Used by active frontend/UI packages and integrations requiring browser/Node ecosystems. Frontend code consumes backend truth and must not duplicate provider routing, memory persistence, policy, or authorization.

### SQL

Used for PostgreSQL/Supabase schema, migrations, functions/policies where applicable. Schema changes belong in migrations, not API startup mutation.

### Shell / Dockerfile / YAML

Operational adapters only. Deployment scripts and Compose do not own application policy.

## 3. Backend framework

### FastAPI

Owns transport/API composition:

- request/response schemas;
- dependency injection at HTTP boundary;
- auth/session/tenant context resolution;
- route registration;
- exception translation;
- health/readiness/metrics HTTP surfaces.

FastAPI routes do not own AI orchestration.

### Uvicorn

Canonical ASGI server target:

```text
ai_karen_engine.app:create_app
```

Do not introduce a custom process manager to re-own application startup.

## 4. AI/model interfaces

### Provider abstraction

Models/providers execute behind the canonical model runtime. Supported provider styles may include:

- local model runtimes;
- OpenAI-compatible HTTP endpoints;
- Transformers-backed execution where configured;
- Ollama where configured;
- external providers only when enabled.

vLLM is integrated as an OpenAI-compatible endpoint, not a `builtin_vllm` authority.

### LangChain

Use only specific components when useful. Do not make LangChain the provider registry, prompt authority, memory store, or global runtime.

### LangGraph

Use for explicit graph workflow semantics only. See `REASONING_LANGGRAPH_MEDUSA.md`.

## 5. Data interfaces

### PostgreSQL / Supabase

Primary durable data platform where configured. Used for durable application/memory state and schema authority.

### Redis

Ephemeral/bounded state, cache, session/runtime acceleration where configured. Redis is not the durable memory source of truth.

### Object storage

Artifacts/media/files where required by the owning domain.

### Retired memory infrastructure

Milvus and Elasticsearch are not current memory dependencies.

## 6. HTTP/API surface conventions

### `/api/...`

Application/domain APIs.

Examples by ownership:

```text
/api/auth/*          authentication/session
/api/extensions/*    extension management
/api/plugins/*       plugin management
/api/health/*        detailed monitoring
/api/admin/* or governed admin routers   privileged operations
```

Exact live route prefixes should be verified from current router wiring before adding a new endpoint.

### Platform endpoints

```text
/health/live   cheap process liveness
/ready         traffic readiness
/metrics       Prometheus exposition
```

These are platform contracts, not domain APIs.

## 7. Repository placement

```text
AI-Karen/
├── PROJECT_DEV_MANIFEST.md        canonical developer contract
├── src/
│   └── ai_karen_engine/
│       ├── app.py                 canonical ASGI entrypoint
│       ├── cli.py                 operator adapter
│       ├── api_routes/            thin HTTP ingress by domain
│       ├── core/
│       │   ├── cortex/            cognitive decisions/policy signals
│       │   ├── runtime/           execution authority
│       │   ├── model_runtime/     model/provider runtime
│       │   ├── memory/            memory domain
│       │   ├── reasoning...       cognitive/reasoning components
│       │   └── langgraph...       graph workflow integration
│       ├── agent_medusa/          multi-agent topology
│       ├── extensions/            extension kernel/runtime/contracts
│       ├── config/                canonical configuration
│       ├── auth/                  authentication support
│       ├── platform/
│       │   └── observability/     telemetry/metrics/diagnostics
│       ├── integrations/          external integration adapters
│       └── server/                canonical/transitional application helpers
├── tests/
│   ├── architecture/              executable authority boundaries
│   └── ...                        unit/integration/domain tests
├── docs/
│   └── development/               current developer contracts
├── supabase/                      schema/migrations/data-plane config
├── scripts/                       operator/build/migration scripts only
├── deploy/                        deployment adapters where present
├── Dockerfile
└── docker-compose*.yml
```

The repository is under active convergence, so verify live directories before creating a new one. A listed directory describes intended ownership, not permission to duplicate an existing implementation.

## 8. Where new code belongs

### New API endpoint

Put transport code under the relevant `api_routes/<domain>/` area and delegate to the existing runtime/domain service.

### New cognitive concept

Search canonical cognitive/contracts/CORTEX definitions first. Extend the canonical type instead of introducing an agent- or graph-specific duplicate.

### New provider

Register/adapt through model runtime/provider contracts. Do not add provider selection code to routes or UI.

### New prompt

Register through canonical prompt registry/contracts. Do not embed prompt authority in the provider/route/agent.

### New memory behavior

Extend the memory domain/recall/governance owner. Do not add another store because a framework offers one.

### New graph workflow

Place behind the canonical LangGraph orchestration boundary only if graph semantics are required.

### New specialist agent

Define/register through AgentMedusa's governed definition path. Reference prompt/tool permissions rather than embedding global authority.

### New extension/tool/action

Use the canonical extension registry/manifest and ActionExecutionGate path.

### New metric/event

Use `platform/observability`. Verify bounded labels and existing canonical metric vocabulary first.

### New configuration

Add to canonical config with safe default, env override, validation, documentation, and failure semantics.

## 9. External API integration rules

External API clients belong in integration/provider/extension adapters according to responsibility.

They must define:

- timeout;
- retry semantics when safe;
- authentication/credential source;
- error translation;
- rate-limit handling;
- cancellation behavior;
- observability;
- tenant/user scope where applicable.

Do not make raw external HTTP calls from UI or route code when a governed backend adapter should own them.

## 10. Dependency rule

Before adding a package:

1. identify the specific capability gap;
2. prove no existing dependency/module satisfies it;
3. ensure it does not become architecture authority;
4. confirm license/security/runtime implications;
5. add it through the canonical dependency system once that system is established;
6. add tests around the adapter/contract, not the library internals.

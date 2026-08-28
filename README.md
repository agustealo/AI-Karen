# AI Karen

**AI Karen is a local-first, prompt-first AI runtime for governed execution, durable memory, provider orchestration, multi-agent coordination, extensibility, and observable system behavior.**

The repository is in active architecture convergence. The goal is not to accumulate frameworks. Every major responsibility should have one owner, one runtime path, one registry/config source, and executable proof.

## Core principles

- **Local-first:** prefer healthy local inference and infrastructure when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable execution contracts.
- **Runtime-authoritative:** routes, UI, providers, agents, and plugins do not become alternate runtimes.
- **CORTEX decides, Runtime executes:** cognitive decisions remain separate from execution authority.
- **RuntimePolicy authorizes:** cognition never authorizes itself.
- **One responsibility, one owner:** duplicate orchestrators, registries, loaders, and fallback paths are collapsed.
- **Security by enforcement:** RBAC, tenant isolation, sessions, permissions, and audit are backend responsibilities.
- **Observable by default:** provider, model, memory, agent, plugin, fallback, degradation, and request paths are traceable.
- **Honest degradation:** unavailable capability is reported as degraded/unavailable, never fabricated as model output.
- **Test-proven architecture:** contracts are executable wherever practical.

## Architecture

Karen's canonical core follows this authority chain:

```text
Intelligence
     |
Personalization ----+
Adaptive -----------+--> CORTEX --> RuntimePolicy --> ChatRuntime
                                              |
                                              +--> direct model execution
                                              +--> reasoning
                                              +--> LangGraph workflows
                                              +--> Agent Medusa
                                              +--> tools / extensions
```

### Ownership summary

| Responsibility | Canonical owner |
|---|---|
| HTTP ingress | `src/ai_karen_engine/api_routes/` |
| Request lifecycle/execution | `src/ai_karen_engine/core/runtime/` |
| Cognitive decisions | `src/ai_karen_engine/core/cortex/` |
| ML/signal extraction | `src/ai_karen_engine/core/intelligence/` |
| Runtime authorization | `src/ai_karen_engine/core/runtime/policy/` |
| Prompt assembly | canonical runtime prompt layer |
| Provider/model runtime | canonical model runtime + provider registry |
| Memory | layered memory runtime, NeuroRecall, MemoryFormation, NeuroVault |
| Multi-agent execution | Agent Medusa |
| Graph workflows | LangGraph only for true graph semantics |
| Extensions/actions | governed extension/action runtime |
| Configuration | `src/ai_karen_engine/config/` + deployment environment adapter |
| Observability | canonical platform observability layer |

Routes remain thin. The UI displays backend truth. CORTEX does not execute providers/tools/plugins. RuntimePolicy remains the authorization authority.

## First-run system

KAREN has a **first-class first-run lifecycle**, not merely a setup endpoint.

The lifecycle is:

```text
validated production config
        -> canonical migrations
        -> API/auth readiness
        -> durable owner required?
        -> create first owner + tenant through AuthService
        -> resolve backend RBAC + issue HTTP-only session
        -> verify first-run closes
        -> restart exact production image
        -> prove durable login after restart
        -> verify optional runtime capabilities independently
```

The four lifecycle states are:

1. **BOOTSTRAP_BLOCKED**: production config, storage, migrations, or auth readiness is unavailable.
2. **OWNER_REQUIRED**: the platform can bootstrap but no durable user exists.
3. **OWNER_CREATED**: the initial owner, tenant, RBAC context, and authenticated session are durable.
4. **OPERATIONAL**: owner state survives restart and normal login works.

Provider/model availability is deliberately **not** part of `first_run_required`. A securely initialized installation may have a model provider in an explicit degraded/unavailable state. Auth bootstrap must never choose providers, download models, execute plugins, or mutate memory.

Canonical contract: `docs/architecture/FIRST_RUN_SYSTEM.md`.

### First-run security invariants

Production bootstrap must keep all development bypasses disabled:

```text
ENVIRONMENT=production
DEBUG=false
AUTH_DEV_MODE=false
AUTH_ALLOW_DEV_LOGIN=false
KARI_AUTH_BYPASS=false
AUTH_ENABLE_SESSION_VALIDATION=true
AUTH_AUTO_CREATE_TABLES=false
```

Schema ownership stays with canonical migrations. Production first run must not depend on route-level DDL or hard-coded development credentials.

## Quick start

### Requirements

- Python 3.10+
- Docker with Docker Compose
- Optional NVIDIA GPU for GPU-local model workflows

### 1. Clone and configure

```bash
git clone https://github.com/agustealo/AI-Karen.git
cd AI-Karen
cp .env.example .env
```

Replace example secrets before production use. Never commit real credentials.

### 2. Validate deployment configuration

Development/core composition:

```bash
docker compose config
```

Production composition:

```bash
cp .env.production.example .env.production
# replace every example secret/value before real deployment

docker compose \
  --env-file .env.production \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.prod.yml \
  config
```

### 3. Start the stack

Core stack:

```bash
docker compose up
```

CPU overlay:

```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.cpu.yml up
```

CUDA overlay:

```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.cuda.yml up
```

Optional profiles are enabled explicitly, for example:

```bash
docker compose --profile observability up -d
docker compose --profile ollama up -d ollama
docker compose --profile vllm up -d vllm
```

### 4. Verify liveness and auth readiness

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/api/auth/health
```

OpenAPI is available at:

```text
http://localhost:8000/docs
```

### 5. Check first-run state

```bash
curl http://localhost:8000/api/auth/first-run
```

A fresh installation should report:

```json
{
  "first_run_required": true,
  "message": "First-run setup required"
}
```

### 6. Create the initial administrator

Canonical endpoint:

```text
POST /api/auth/first-run/setup
```

Example:

```bash
curl -X POST http://localhost:8000/api/auth/first-run/setup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "full_name": "Your Name",
    "password": "choose-a-strong-password",
    "confirm_password": "choose-a-strong-password"
  }'
```

The backend creates the durable first user through the canonical `AuthService`, assigns tenant scope, resolves RBAC permissions, returns an authenticated session, and sets the `kari_session` HTTP-only cookie.

### 7. Verify bootstrap closed

```bash
curl http://localhost:8000/api/auth/first-run
```

It should now report `first_run_required: false`.

Use the returned session/token to verify:

```text
GET /api/auth/me
```

### 8. Open the UI

```text
http://localhost:8010
```

Login uses the email or generated username plus the password created during first run.

### 9. Verify desired capabilities

After secure bootstrap, independently verify the capabilities your deployment actually uses:

- provider/model health from the canonical model runtime;
- PostgreSQL/Redis and durable-memory dependencies when enabled;
- governed extension manifests/permissions for enabled extensions;
- metrics/audit export required by deployment policy.

The UI must display these backend states honestly. It must not create alternate provider, memory, extension, or readiness truth.

## Production first-run proof

KAREN's first-run proof uses an isolated real container stack with a fresh database. It applies canonical migrations, boots the production API image, creates the first owner, proves authenticated tenant scope, restarts the API, and proves normal login survives restart.

Run the static architecture guard:

```bash
python scripts/ci/validate_first_run_contract.py
```

Validate the smoke harness:

```bash
bash -n scripts/ci/production-first-boot-smoke.sh
```

Execute the real production boot proof:

```bash
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:first-run .
KAREN_SMOKE_API_IMAGE=ai-karen-api:first-run \
  bash scripts/ci/production-first-boot-smoke.sh
```

CI owner: `.github/workflows/production-first-boot-smoke.yml`.

## Memory

Karen keeps memory responsibilities distinct:

- **STM:** recent conversation/session state.
- **Episodic:** meaningful interactions and decisions.
- **LTM:** durable facts/preferences.
- **NeuroRecall:** retrieval strategy and ranking, not a duplicate store.
- **MemoryFormation:** post-outcome formation decision.
- **NeuroVault:** governed durable persistence, recovery, archive, and deletion semantics.

Memory access must remain tenant-aware, authorization-sensitive, provenance-preserving, and auditable.

## Extensions

The governed extension path is:

```text
manifest
  -> validation
  -> registry/lifecycle
  -> RuntimePolicy authorization
  -> ActionExecutionGate
  -> execution
  -> output validation
  -> audit / telemetry
```

Manifest declaration is not authorization.

## Observability

Important runtime metadata includes:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
intent
topology
provider
model
runtime_engine
fallback_level
degraded_mode
response_source
memory_recall_count
plugin_id
agent_id
latency_ms
status
error_code
```

Prometheus is the canonical numeric metrics backend. Grafana is optional through the observability profile.

Default development endpoints:

| Service | Address |
|---|---|
| Web UI | http://localhost:8010 |
| API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |

## Repository layout

```text
AI-Karen/
├── src/
│   ├── ai_karen_engine/
│   │   ├── api_routes/
│   │   ├── auth/
│   │   ├── config/
│   │   ├── core/
│   │   │   ├── cognitive/
│   │   │   ├── cortex/
│   │   │   ├── intelligence/
│   │   │   ├── memory/
│   │   │   ├── model_runtime/
│   │   │   ├── reasoning/
│   │   │   └── runtime/
│   │   ├── agent_medusa/
│   │   └── server/
│   └── ui_launchers/Karen-AI-Theme/
├── tests/
├── docs/
├── scripts/
├── supabase/migrations/
├── Dockerfile
├── docker-compose.yml
├── PROJECT_DEV_MANIFEST.md
└── README.md
```

## Development rules

Before adding a service, registry, orchestrator, helper, route, provider, config path, or bootstrap mechanism:

1. Find the current owner.
2. Search for the strongest existing implementation.
3. Extend the canonical implementation.
4. Keep routes thin and UI display-only.
5. Preserve tenant isolation, RBAC, audit, correlation IDs, and telemetry.
6. Keep provider/model selection inside canonical runtime/model authority.
7. Keep CORTEX decision-only and Runtime execution-authoritative.
8. Delete replaced/dead paths only after reference audit.
9. Prove behavior with tests and architecture contracts.

## Verification

Backend/core:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
python scripts/ci/validate_first_run_contract.py
```

Active frontend package:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm test
npm run build
```

## Canonical documentation

- `PROJECT_DEV_MANIFEST.md` - canonical developer/architecture contract.
- `docs/architecture/FIRST_RUN_SYSTEM.md` - first-run ownership, lifecycle, security, readiness, and proof.
- `src/ai_karen_engine/core/ARCHITECTURE.md` - core authority matrix.
- `src/ai_karen_engine/core/README.md` - core-domain ownership.
- `src/ai_karen_engine/config/README.md` - configuration ownership.

## License

See the repository license files for licensing terms.

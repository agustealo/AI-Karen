# AI Karen

**AI Karen is a local-first, prompt-first AI runtime for governed chat execution, durable memory, provider/model orchestration, reasoning, multi-agent workflows, extensions, RBAC, and observable system behavior.**

The project is in active architecture convergence. The objective is not to collect more frameworks. Every major responsibility should have one clear owner, one runtime path, one registry/config source where applicable, and executable proof that the boundary holds.

## Core Principles

- **Local-first:** prefer healthy local inference and local infrastructure when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable execution contracts.
- **Runtime-authoritative:** routes, UI, providers, agents, and extensions do not become alternate chat runtimes.
- **CORTEX decides, Runtime executes:** cognition and execution remain separate authorities.
- **RuntimePolicy authorizes:** CORTEX does not authorize itself.
- **One responsibility, one owner:** duplicate orchestrators, registries, loaders, and fallback paths are collapsed rather than preserved indefinitely.
- **Secure by enforcement:** RBAC, tenant isolation, session validation, audit, secrets, and action permissions are backend responsibilities.
- **Observable by default:** provider, model, memory, reasoning, agent, extension, fallback, and degradation paths should be traceable.
- **Honest degradation:** unavailable capability returns explicit degraded/unavailable state rather than fabricated model output.
- **Test-proven architecture:** imports, routing, fallbacks, memory, RBAC, first-run, API contracts, UI contracts, and deployment paths should have executable proof.

## Canonical Architecture

Karen's core follows a six-layer model:

```text
1. Intelligence         senses   -> What is this request?
2. Decision             decides  -> What should Karen do?
3. Execution            acts     -> Execute the authorized decision
4. Specialist Engines   serve    -> Models, reasoning, agents, tools, workflows
5. State                retains  -> Memory, recall, persistence, governance
6. Platform Kernel      governs  -> Security, observability, config, infrastructure
```

The authority chain is approximately:

```text
Intelligence
     |
Personalization ----+
Adaptive -----------+--> CORTEX --> RuntimePolicy --> ChatRuntime
                                              |
                                              +--> Direct model execution
                                              +--> Reasoning
                                              +--> LangGraph workflows
                                              +--> Agent Medusa
                                              +--> Tools / Extensions
```

### CORTEX

`src/ai_karen_engine/core/cortex/` is the cognitive decision authority. It interprets intent, capability requirements, topology, reasoning needs, memory-routing signals, ambiguity, and execution recommendations. It does **not** execute providers, tools, plugins, memory writes, or agents.

### Chat Runtime

`src/ai_karen_engine/core/runtime/` is the live request/execution authority. It owns request normalization, execution context, memory coordination, prompt/context handoff, policy consumption, provider/model execution, streaming, persistence coordination, degradation metadata, telemetry, and audit lifecycle.

API routes stay thin.

### Model Runtime

Provider and model availability, health, inventory, selection, execution, and fallback belong to the canonical model-runtime/provider registry. The UI displays backend truth rather than inventing model availability.

Local-first fallback remains policy/config driven. No fallback may silently manufacture a model answer.

### Agent Medusa and LangGraph

Agent Medusa is a governed multi-agent execution topology, not a second runtime or policy engine.

LangGraph is reserved for real graph semantics such as branching plans, checkpoint/resume, long-running workflows, human gates, and stateful tool chains. Ordinary chat does not require LangGraph.

## Memory

Karen separates memory responsibilities:

- **STM:** recent conversation/session state.
- **Episodic:** meaningful interactions, decisions, and outcomes.
- **LTM:** durable facts, preferences, and knowledge.
- **NeuroRecall:** retrieval strategy, ranking, and recall signals.
- **MemoryFormation + NeuroVault:** governed durable mutation, lifecycle, recovery, and deletion semantics.

Memory access and persistence must remain tenant-aware, policy-governed, and auditable.

## Extensions

The canonical extension path is governed:

```text
manifest
 -> validation
 -> registry
 -> lifecycle
 -> RuntimePolicy authorization
 -> ActionExecutionGate
 -> execution
 -> output validation
 -> audit / telemetry
```

Manifest declaration is not authorization.

## First Run Is a Production Contract

KAREN treats first run as an installation lifecycle, not a welcome screen.

A fresh installation is only correctly bootstrapped when the migration-owned auth schema is ready, a durable installation tenant exists, exactly one first owner can be created through the canonical auth authority, bootstrap cannot be re-entered after completion, authenticated identity works, and that state survives process restart.

Canonical ownership is:

```text
migrations/deployment tooling
  -> create/upgrade schema

AuthService.initialize
  -> validate auth config
  -> verify migration-owned auth tables

GET /api/auth/first-run
  -> AuthService.is_first_run()

POST /api/auth/first-run/setup
  -> transaction advisory lock
  -> re-check durable user count
  -> create/resolve durable installation tenant
  -> create verified admin + user owner
  -> audit
  -> normal authentication/session issuance
```

The auth route does not create tenant/user records directly. The UI must not infer first-run state from local storage or failed login attempts. Production runtime does not create missing auth tables as a convenience fallback.

The executable production proof is:

```text
scripts/ci/production-first-boot-smoke.sh
.github/workflows/production-first-boot-smoke.yml
```

That smoke starts fresh PostgreSQL/pgvector and password-protected Redis, applies canonical migrations, boots the real production image, creates the first owner, proves duplicate setup is denied, verifies exactly one durable bootstrap user, restarts the exact image, and proves the owner plus completed first-run state survive restart.

See `docs/architecture/FIRST_RUN_SYSTEM.md` for the full authority, security, UI, observability, and proof contract.

## Repository Layout

Canonical application code lives under `src/`.

```text
AI-Karen/
├── src/
│   ├── ai_karen_engine/
│   │   ├── core/
│   │   │   ├── cortex/
│   │   │   ├── intelligence/
│   │   │   ├── runtime/
│   │   │   ├── model_runtime/
│   │   │   ├── reasoning/
│   │   │   ├── memory/
│   │   │   ├── cognitive/
│   │   │   ├── context/
│   │   │   └── personalization/
│   │   ├── agent_medusa/
│   │   ├── api_routes/
│   │   ├── config/
│   │   ├── services/
│   │   └── platform/
│   └── ui_launchers/
│       └── Karen-AI-Theme/
├── tests/
├── docs/
├── scripts/
├── deploy/
├── config_assets/
├── supabase/
├── Dockerfile
├── docker-compose.yml
├── PROJECT_DEV_MANIFEST.md
└── README.md
```

## Quick Start

### Requirements

- Python 3.10+
- Docker with Docker Compose
- Optional NVIDIA GPU for CUDA/vLLM workflows

### 1. Clone and configure

```bash
git clone https://github.com/agustealo/AI-Karen.git
cd AI-Karen
cp .env.example .env
```

Review `.env` before startup. Replace production secrets and never commit real credentials.

### 2. Start the stack

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

Optional services are enabled through their Compose profiles when required by the deployment.

### 3. Verify liveness and auth readiness

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/api/auth/health
```

If auth readiness fails, fix configuration/database/migration state before trying to bootstrap an owner. First run is fail-closed.

### 4. Check first-run state

```bash
curl http://localhost:8000/api/auth/first-run
```

A fresh installation should return:

```json
{
  "first_run_required": true,
  "message": "First-run setup required"
}
```

### 5. Create the first owner

```bash
curl -X POST http://localhost:8000/api/auth/first-run/setup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "full_name": "Your Name",
    "password": "Choose-A-Strong-Pass9!",
    "confirm_password": "Choose-A-Strong-Pass9!"
  }'
```

The canonical auth service creates the installation tenant and verified first owner with `admin` and `user` roles, then authenticates through the normal session path. Bootstrap is transaction-serialized across workers. Once a durable user exists, later first-run setup attempts are rejected.

### 6. Open the UI

```text
http://localhost:8010
```

Log in with the email or generated username plus the password created during first run.

### 7. Verify installation readiness after login

Identity bootstrap does not take ownership of unrelated subsystems. Verify backend truth for the capabilities your deployment requires:

1. **Provider availability:** at least one intended provider is enabled and healthy.
2. **Model configuration:** the desired local/default model is discoverable and eligible.
3. **Memory services:** durable memory dependencies are healthy when enabled.
4. **Extensions:** only governed, validated extensions required for the deployment are enabled.
5. **Observability:** metrics/logging/tracing required by the environment are reachable.
6. **Secrets/security:** production JWT, database, Redis, extension, provider, and dashboard secrets are non-example values.
7. **First real chat:** submit a request through the canonical `/api/chat` runtime and verify the response provenance/degradation metadata reflects the provider/model that actually executed.

A future typed installation-readiness view may aggregate those subsystem health signals, but it must not become a second provider, memory, extension, or observability authority.

## Production Deployment

Example production Compose startup:

```bash
cp .env.example .env
# Edit .env with production values first.

docker compose -f docker-compose.yml -f deploy/compose/docker-compose.prod.yml up -d
```

Production/staging auth configuration validates secrets and fails closed. Migration-owned schema must be applied before first-run owner creation.

## Default Development Endpoints

| Service | Address |
|---|---|
| Web UI | http://localhost:8010 |
| API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |

Optional services are available only when their corresponding profiles are enabled.

## Configuration

Canonical configuration code lives under:

```text
src/ai_karen_engine/config/
```

Deployment-specific overrides and secrets come from validated environment/config adapters. Application subsystems should not scatter direct environment reads when a canonical configuration contract exists.

Known cleanup debt is tracked in `PROJECT_DEV_MANIFEST.md`, including remaining direct configuration reads that have not yet been migrated.

## Security

KAREN's protected execution paths preserve:

- authentication and session validation;
- RBAC;
- durable tenant isolation;
- least privilege;
- secret redaction;
- tool/extension permission gates;
- audit logging;
- safe error translation;
- request/correlation identity;
- fail-closed production behavior.

Frontend checks are presentation only. Privileged authority is backend-owned.

## Observability

Runtime events should make it possible to determine what actually happened, including request/correlation identity, tenant/user/session/conversation scope, intent/topology, provider/model/runtime engine, fallback/degradation, memory/extension/agent participation, latency, status, and error reason.

Prometheus is the canonical numeric metrics backend. Grafana is optional through the observability profile. High-cardinality request/user identifiers belong in structured logs/traces rather than Prometheus labels.

## Verification

Core gates:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
```

Frontend gates from the active UI package:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

First-run architecture contract:

```bash
pytest tests/architecture/test_first_run_system_contract.py -q
bash -n scripts/ci/production-first-boot-smoke.sh
```

Real production first-run burn:

```bash
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:beta .
KAREN_SMOKE_API_IMAGE=ai-karen-api:beta bash scripts/ci/production-first-boot-smoke.sh
```

Do not report a release path green unless the exact-head CI/proof actually passed.

## Development Rules

Before adding a service, registry, orchestrator, helper, route, provider, config path, setup wizard, or fallback:

1. Identify the current owner.
2. Search for a stronger existing implementation.
3. Extend the canonical owner rather than creating a parallel path.
4. Preserve RBAC, tenant scope, audit, credentials, and telemetry.
5. Keep API routes thin.
6. Keep provider/model decisions out of UI.
7. Keep CORTEX decision-only.
8. Keep Runtime execution-authoritative.
9. Keep migrations authoritative for production schema.
10. Prove the boundary with executable tests/burns.
11. Delete dead/duplicate code only after reference and replacement audit.

## Architecture Documentation

Read these first:

- `PROJECT_DEV_MANIFEST.md` for the canonical developer contract and live truth map.
- `docs/architecture/FIRST_RUN_SYSTEM.md` for installation/bootstrap authority and proof.
- `docs/development/ARCHITECTURE_AUTHORITY.md` for architectural ownership rules.
- `src/ai_karen_engine/core/ARCHITECTURE.md` for core authority boundaries.
- `src/ai_karen_engine/core/README.md` for core-domain ownership.
- `src/ai_karen_engine/config/README.md` for configuration ownership.

Historical sprint sheets are implementation history, not architecture authority.

## License

See the repository license files for licensing terms.

<p align="center">
  <img src="src/ui_launchers/Karen-AI-Theme/public/brand/karen-banner.svg" alt="KAREN. Local by default. Governed by design." width="100%" />
</p>

<p align="center">
  <strong>Local-first · Prompt-first · Runtime-authoritative · Governed memory · Provider orchestration · RBAC · Observable execution</strong>
</p>

# KAREN

KAREN is a local-first, prompt-first AI runtime for governed chat execution, durable memory, provider/model orchestration, agents, workflows, extensions, and observable automation.

It is built around a simple rule: **one responsibility → one owner → one runtime path → executable proof.** KAREN is not a pile of interchangeable AI frameworks. The system separates cognition, authorization, execution, state, infrastructure, and presentation so each can evolve without becoming a second authority.

> **Local by default. Governed by design.**

## Why the name works

The familiar "Karen" meme is about escalation and asking for the manager. KAREN flips that idea without turning the product into a joke: it is the composed systems operator that knows who owns the responsibility, routes work to the correct authority, applies policy, and preserves execution truth.

The canonical identity is deliberately abstract. There is no literal meme face or novelty mascot. The K-shaped mark encodes a stable runtime spine, routed branches, and a governed handoff node. The subtle arc is the only wink to the cultural reference, keeping the identity recognizable without dating it to the meme cycle.

- [Brand system](docs/presentation/BRAND_SYSTEM.md)
- [Product presentation manifest](docs/presentation/PRODUCT_PRESENTATION_MANIFEST.md)
- [Screenshot provenance and capture contract](docs/assets/screenshots/README.md)

## Core principles

- **Local-first:** prefer healthy local inference and local infrastructure when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable execution contracts rather than scattered string construction.
- **Runtime-authoritative:** routes, UI, providers, agents, and extensions do not become alternate chat runtimes.
- **CORTEX decides, Runtime executes:** cognitive classification, routing, and policy recommendations remain separate from execution.
- **RuntimePolicy authorizes:** decision components do not authorize their own actions.
- **One responsibility, one owner:** duplicate orchestrators, registries, loaders, persistence paths, and fallbacks are collapsed into canonical owners.
- **Secure by enforcement:** RBAC, tenant isolation, session validation, audit, secret handling, and action permissions are backend responsibilities.
- **Observable by default:** provider, model, memory, reasoning, agent, extension, fallback, and degradation paths should be traceable.
- **Honest degradation:** unavailable capability returns explicit degraded or unavailable state rather than fabricated model output or UI truth.
- **Test-proven architecture:** routing, fallbacks, memory, RBAC, first-run, API contracts, UI contracts, and deployment paths require executable proof.

## Product surfaces

The current web application exposes real product surfaces rather than marketing-only mockups:

| Surface | What it represents |
|---|---|
| **Chat** | Canonical conversation runtime and model execution path |
| **Comms Center** | Communication-oriented workspace inside the authenticated application |
| **Agents Overview** | Governed agent and workflow visibility |
| **Agents / Tasks / Jobs / Cron Jobs** | Operational workflow surfaces backed by application runtime state |
| **Plugin Overview** | Governed extension/plugin surface |
| **Application Settings** | User-facing configuration that must reflect backend truth |
| **My Account** | Authenticated identity/account surface |

### Real screenshots only

KAREN does not use generated dashboards, design mockups, generic Playwright reports, or browser-test failure artifacts as product evidence. A dedicated Playwright showcase rail captures the real authenticated UI against a real running stack and writes the canonical gallery to `docs/assets/screenshots/`.

```bash
cd src/ui_launchers/Karen-AI-Theme

KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_EMAIL='<sanitized-demo-email>' \
KAREN_SHOWCASE_PASSWORD='<sanitized-demo-password>' \
KAREN_SHOWCASE_TARGET_REVISION='<full-40-character-deployed-sha>' \
KAREN_SHOWCASE_BASE_URL='http://localhost:8010' \
npm run showcase:capture
```

The capture rail is intentionally fail-closed. It records the capture-harness checkout separately from the operator-attested deployed revision, and it will not silently substitute fake media when a real sanitized environment is unavailable.

## Canonical architecture

KAREN's core follows a six-layer model:

```text
1. Intelligence         senses   -> What is this request?
2. Decision             decides  -> What should KAREN do?
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

KAREN separates memory responsibilities:

- **STM:** recent conversation/session state.
- **Episodic:** meaningful interactions, decisions, and outcomes.
- **LTM:** durable facts, preferences, and knowledge.
- **NeuroRecall:** retrieval strategy, ranking, and recall signals.
- **MemoryFormation + NeuroVault:** governed durable mutation, lifecycle, recovery, and deletion semantics.

Memory access and persistence remain tenant-aware, policy-governed, and auditable.

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

## First run is a production contract

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

The production smoke starts fresh PostgreSQL/pgvector and password-protected Redis, applies canonical migrations, boots the real production image, creates the first owner, proves duplicate setup is denied, verifies durable bootstrap state, restarts the exact image, and proves the owner plus completed first-run state survive restart.

See `docs/architecture/FIRST_RUN_SYSTEM.md` for the full authority, security, UI, observability, and proof contract.

## Repository layout

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
│   │   │   └── personalization/
│   │   ├── agent_medusa/
│   │   ├── api_routes/
│   │   ├── config/
│   │   └── platform/
│   └── ui_launchers/
│       └── Karen-AI-Theme/
├── tests/
├── docs/
├── scripts/
├── deploy/
├── config_assets/
├── PROJECT_DEV_MANIFEST.md
└── README.md
```

## Install, first-time setup, and run

This is the supported operator path for a fresh KAREN installation. The goal is not merely to start containers: a healthy first run has migrated infrastructure, durable authentication, a real installation tenant, a first owner/admin, an eligible provider/model, and a successful chat through the canonical runtime.

For the deeper authority and security contract, see [KAREN First-Run System](docs/architecture/FIRST_RUN_SYSTEM.md).

### 1. Prerequisites

Required for the normal containerized path:

- **Git**
- **Docker** with Docker Compose v2
- **Python 3.10+** for repository utilities, verification, and local development

Useful but not required for the container-only path:

- **Node.js 20+** when developing the web UI outside Docker
- **curl** or another HTTP client for health and bootstrap checks
- **NVIDIA Container Toolkit + compatible GPU** only when using CUDA/vLLM deployment paths

Before starting, confirm Docker is healthy:

```bash
docker version
docker compose version
```

### 2. Clone KAREN

```bash
git clone https://github.com/agustealo/AI-Karen.git
cd AI-Karen
```

### 3. Create the environment file

For a local/development installation:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Review `.env` before startup. At minimum, make sure database, Redis, auth, provider/model, and any enabled external-service settings match the machine you are actually running.

Important rules:

- never commit real passwords, API keys, tokens, or production secrets;
- do not leave production deployments on example/default secrets;
- keep provider/model configuration in the canonical backend configuration/runtime path;
- do not enable development auth bypasses in production;
- if an optional subsystem is disabled, do not fabricate readiness for it.

### 4. Choose the runtime profile

The normal local stack:

```bash
docker compose up -d
```

CPU-oriented overlay:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.cpu.yml \
  up -d
```

CUDA-oriented overlay:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.cuda.yml \
  up -d
```

Optional services remain profile/config driven. Do not enable an optional provider, model runtime, plugin, or observability service merely to make the UI look configured.

### 5. Watch startup

Check running services:

```bash
docker compose ps
```

Follow logs when diagnosing startup:

```bash
docker compose logs -f
```

For one service:

```bash
docker compose logs -f api
```

The API must not be treated as ready simply because its process exists. KAREN intentionally fails closed when required auth/database state is unavailable.

### 6. Verify backend and authentication readiness

Check basic liveness:

```bash
curl http://localhost:8000/health/live
```

Check canonical authentication readiness:

```bash
curl http://localhost:8000/api/auth/health
```

If auth readiness fails, fix environment, database, or migration state before creating an administrator. First-run bootstrap does not create missing production schema as a convenience fallback.

### 7. Check whether first-run setup is required

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

KAREN derives this state from durable backend truth. Browser storage, failed login attempts, or UI state are not first-run authority.

### 8. Create the first owner/admin

Open the web application:

```text
http://localhost:8010
```

If the active UI presents the first-run flow, use it to create the installation owner. The UI delegates to the same backend authority described below.

The canonical API bootstrap is:

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

This operation is intentionally privileged and one-time. The backend:

1. acquires the bootstrap transaction lock;
2. re-checks that no durable user already owns the installation;
3. creates or resolves the durable installation tenant;
4. creates the verified first owner with backend `admin` and `user` roles;
5. emits the auth audit event;
6. authenticates through the normal session path.

After a successful bootstrap, repeating the first-run setup is rejected.

### 9. Log in and verify the durable identity

Use the owner credentials created above.

You can also verify the authenticated identity through the normal auth API/session path. The important result is that the account is durable, tenant-scoped, and backend-authorized. The frontend does not grant administrative authority by itself.

Restart KAREN and confirm the installation remains configured:

```bash
docker compose restart
```

Then re-check:

```bash
curl http://localhost:8000/api/auth/first-run
```

It should no longer report first-run setup as required.

### 10. Configure and verify the AI provider/model

Identity bootstrap and model setup are separate responsibilities.

After logging in:

1. open **Application Settings**;
2. verify the intended provider is enabled and healthy;
3. verify the intended model is discoverable through backend/model-runtime truth;
4. confirm local endpoint/base URL configuration if using LM Studio, Ollama, llama.cpp, vLLM, or another supported local runtime;
5. add external provider credentials only when that provider is intentionally enabled;
6. do not rely on a frontend-only model entry or fallback label.

Provider selection, availability, fallback, and execution remain owned by the canonical model runtime. A provider shown in the UI is useful only when the backend reports it as actually eligible.

### 11. Verify memory and supporting services

Before calling the installation ready, check the subsystems required by your deployment:

- **PostgreSQL/pgvector:** durable application and memory data
- **Redis:** bounded STM/hot state and distributed coordination
- **MemoryFormation/NeuroVault:** governed durable memory mutation when enabled
- **Plugins/extensions:** only validated and authorized extensions should be enabled
- **Observability:** metrics/logging/tracing services required by your environment
- **Storage/integrations:** only when enabled by configuration

A disabled optional subsystem is acceptable. A silently broken subsystem pretending to be healthy is not.

### 12. Run the first real chat

Use the Chat surface in the web application and submit a real request.

A successful first-chat check should prove:

- the request traveled through the canonical chat runtime;
- an eligible provider/model actually executed;
- the response is not an emergency/canned substitute;
- provider/model/degradation metadata reflects what really happened;
- the conversation is durably persisted;
- a second turn can use the prior durable transcript when policy allows.

If the chat reports no eligible model/provider, fix provider/model configuration instead of adding route-level or UI fallbacks.

### 13. Normal run commands

Start in the background:

```bash
docker compose up -d
```

See service state:

```bash
docker compose ps
```

Follow logs:

```bash
docker compose logs -f
```

Restart:

```bash
docker compose restart
```

Stop while preserving durable volumes:

```bash
docker compose down
```

Rebuild after code/dependency changes:

```bash
docker compose build
docker compose up -d
```

Do not delete database/model volumes as a routine troubleshooting step. Treat destructive storage cleanup as an explicit reset operation because it can remove durable installation state.

### 14. First-time administrator checklist

Before inviting other users or relying on KAREN operationally, confirm:

- [ ] environment file reviewed and secrets replaced where required;
- [ ] Docker/Compose configuration validates;
- [ ] API liveness is healthy;
- [ ] auth health is ready;
- [ ] first owner/admin was created through canonical first-run bootstrap;
- [ ] first-run cannot be re-entered after setup;
- [ ] owner identity survives restart;
- [ ] intended provider is healthy;
- [ ] intended model is discoverable and eligible;
- [ ] Redis and PostgreSQL-backed state are healthy;
- [ ] required memory/extension/observability services are healthy;
- [ ] first real chat succeeds through the actual runtime;
- [ ] conversation continuity works on a second turn;
- [ ] logs/telemetry do not expose secrets;
- [ ] production deployments do not use development auth bypasses.

### 15. Common first-run failures

**`/health/live` fails**

Inspect the API/container logs first:

```bash
docker compose ps
docker compose logs api
```

Treat dependency/configuration errors as real startup failures.

**`/api/auth/health` is not ready**

Verify database connectivity, migrations, auth configuration, and required secrets. Do not bypass the check by creating users manually in the route/UI.

**`first_run_required` is unexpectedly false**

The durable database already contains one or more users. Confirm that you are connected to the intended database before making changes.

**First-admin creation is rejected**

Re-check first-run state and backend logs. A concurrent or previously completed bootstrap is deliberately denied.

**The UI loads but chat cannot answer**

Check backend provider/model availability. UI reachability does not prove inference readiness.

**The model exists locally but KAREN cannot reach it**

Verify the configured provider base URL from the environment/runtime context where the API is running. Remember that `localhost` inside a container refers to that container, not automatically to the host machine.

**A restart loses identity or conversation state**

Treat that as a persistence/deployment defect. Confirm the expected PostgreSQL/Redis volumes and connection settings instead of accepting a fresh bootstrap as normal behavior.

### 16. Production deployment

Production uses the production environment template and production Compose overlay:

```bash
cp .env.production.example .env.production
```

Before starting production, replace every required `CHANGE_ME`, example secret, placeholder URL, database credential, Redis credential, provider secret, and public scheme value with deployment-specific values.

Validate the fully rendered Compose contract before starting anything:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.prod.yml \
  config
```

Then start:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.prod.yml \
  up -d
```

After startup, repeat the same readiness sequence used above:

```text
/health/live
-> /api/auth/health
-> /api/auth/first-run
-> first owner bootstrap if required
-> authenticated login
-> provider/model readiness
-> first real chat
-> restart/persistence confirmation
```

Production/staging authentication validates configuration and fails closed. Canonical migrations remain authoritative for schema creation and upgrades. The runtime must not invent missing auth tables, users, tenants, provider state, or successful persistence.

### 17. Production first-run proof

The repository includes a real production bootstrap smoke:

```bash
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:beta .
KAREN_SMOKE_API_IMAGE=ai-karen-api:beta bash scripts/ci/production-first-boot-smoke.sh
```

That proof exercises fresh PostgreSQL/pgvector, password-protected Redis, canonical migrations, first-owner creation, duplicate-bootstrap denial, authenticated identity, process restart, and durable first-run completion.

Fast architecture-level checks:

```bash
pytest tests/architecture/test_first_run_system_contract.py -q
bash -n scripts/ci/production-first-boot-smoke.sh
```

## Default development endpoints

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

Canonical application configuration lives under:

```text
src/ai_karen_engine/config/
```

Environment-specific values and secrets enter through validated configuration adapters and deployment files. Subsystems should not scatter direct environment reads when a canonical configuration contract already exists. Remaining configuration-convergence debt belongs in `PROJECT_DEV_MANIFEST.md`, not in parallel helpers or UI fallbacks.

## Security

KAREN's protected execution paths preserve authentication/session validation, RBAC, durable tenant isolation, least privilege, secret redaction, extension permission gates, audit logging, safe error translation, request/correlation identity, and fail-closed production behavior.

Frontend checks are presentation only. Privileged authority is backend-owned.

## Observability

Runtime events should make it possible to determine what actually happened, including request/correlation identity, tenant/user/session/conversation scope, intent/topology, provider/model/runtime engine, fallback/degradation, memory/extension/agent participation, latency, status, and error reason.

Prometheus is the canonical numeric metrics backend. High-cardinality request/user identifiers belong in structured logs/traces rather than Prometheus labels.

## Verification

The live merge contract is encoded in `.github/workflows/main-quality-gate.yml` and the focused authority workflows. The workflow files, not README prose, are the source of truth for the exact gate set.

The current Main Quality frontend job runs these checks from `src/ui_launchers/Karen-AI-Theme`:

```bash
npm ci --no-audit --no-fund
npm run ci:forbid-mocks
npm run typecheck
node --check server.mjs
npx vitest run --passWithNoTests
npm run build
```

The current backend quality job compiles production Python, runs the correctness-focused Ruff baseline, type-checks the canonical authority contracts, then executes the architecture/runtime/classifier/chat/personalization/memory/tenant proof suites. See the workflow for the exact file and test list.

Useful broad local audits remain:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
```

Those broad commands intentionally surface repository-wide debt beyond the narrower merge-gate baseline. Do not replace an exact-head workflow verdict with a partial local run, and do not describe a broad audit as green unless it actually passed.

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

## Development rules

Before adding or changing a service, registry, orchestrator, helper, route, provider, configuration path, setup flow, or fallback:

1. Identify the current owner of the responsibility.
2. Search for a stronger existing implementation before creating another one.
3. Extend or merge into the canonical owner rather than preserving a parallel path.
4. Preserve RBAC, tenant scope, audit, credential handling, correlation identity, and telemetry.
5. Keep API routes thin and orchestration in the runtime/service owner.
6. Keep provider/model decisions out of the UI. The UI renders backend truth.
7. Keep CORTEX decision-only and Runtime execution-authoritative.
8. Keep schema creation and evolution migration-owned in production.
9. Prefer central config/registry contracts over scattered hardcoded values.
10. Prove the boundary with executable tests, burns, and exact-head CI.
11. Delete dead or duplicate code only after reference audit and replacement proof.

## Architecture documentation

Read these first:

- `PROJECT_DEV_MANIFEST.md` for the canonical developer contract and live truth map.
- `docs/architecture/FIRST_RUN_SYSTEM.md` for installation/bootstrap authority and proof.
- `docs/development/ARCHITECTURE_AUTHORITY.md` for architectural ownership rules.
- `src/ai_karen_engine/core/ARCHITECTURE.md` for core authority boundaries.
- `src/ai_karen_engine/core/README.md` for core-domain ownership.
- `src/ai_karen_engine/config/README.md` for configuration ownership.
- `docs/presentation/BRAND_SYSTEM.md` for visual identity.
- `docs/presentation/PRODUCT_PRESENTATION_MANIFEST.md` for public presentation truth.

Historical sprint sheets are implementation history, not architecture authority.

## License

See the repository license files for licensing terms.

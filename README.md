# AI Karen

**AI Karen is a local-first, prompt-first AI runtime focused on governed execution, durable memory, provider orchestration, multi-agent coordination, extensibility, and observable system behavior.**

The project is currently in an active architecture-convergence phase. The goal is not to accumulate more frameworks. The goal is to make every major responsibility have one clear owner, one runtime path, one registry, one configuration source, and tests that prove the boundaries hold.

## Project Principles

AI Karen is being built around a small set of non-negotiable rules:

- **Local-first**: local inference and local infrastructure are preferred when available.
- **Prompt-first**: prompts are explicit, versioned, testable execution contracts.
- **Runtime-authoritative**: live chat execution is owned by the canonical runtime, not routes, UI code, providers, or agents.
- **CORTEX decides, Runtime executes**: intent, topology, policy signals, and eligibility are separated from execution.
- **One responsibility, one owner**: duplicate orchestrators, registries, loaders, and fallback paths are removed rather than preserved indefinitely.
- **Security by enforcement**: RBAC, tenant isolation, audit, secrets, and action permissions are backend responsibilities.
- **Observable by default**: request, provider, model, memory, agent, plugin, fallback, and degradation paths should be traceable.
- **Honest degradation**: unavailable capabilities return explicit degraded or unavailable state rather than fabricated model output.
- **Test-proven architecture**: imports, routing, fallbacks, memory, RBAC, API contracts, and UI contracts must be verifiable.

## Current Architecture

Karen's canonical core follows a six-layer model:

```text
1. Intelligence         senses   -> What is this request?
2. Decision             decides  -> What should Karen do?
3. Execution            acts     -> Execute the authorized decision
4. Specialist Engines   serve    -> Models, reasoning, agents, tools, workflows
5. State                retains  -> Memory, recall, persistence, governance
6. Platform Kernel      governs  -> Security, observability, config, infrastructure
```

The high-level authority chain is:

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

CORTEX owns decision-making signals such as:

- intent classification
- capability requirements
- execution-topology selection
- reasoning depth
- memory-routing signals
- tool/plugin eligibility signals
- agent-delegation signals
- RBAC-aware execution eligibility

CORTEX **does not execute providers, tools, plugins, or agents**.

### Chat Runtime

`src/ai_karen_engine/core/runtime/` is the live execution authority.

It owns:

- request normalization
- execution context
- memory recall coordination
- prompt/context assembly
- runtime policy consumption
- provider/model execution
- tool and extension execution coordination
- streaming
- persistence
- degradation metadata
- telemetry and audit lifecycle

API routes should remain thin ingress layers.

### Model Runtime

`src/ai_karen_engine/core/model_runtime/` owns provider and inference behavior.

The runtime is designed around centralized provider registration, health, discovery, model inventory, and config-driven fallback behavior.

The intended fallback strategy is local-first and policy-driven:

```text
requested provider/model
    -> local primary
    -> vLLM
    -> Transformers
    -> Ollama when healthy
    -> external provider when enabled
    -> explicit unavailable/degraded result
```

No provider fallback should silently manufacture an answer.

### Agent Medusa

`src/ai_karen_engine/agent_medusa/` is the multi-agent execution topology.

Medusa is **not** a second runtime and **not** a policy engine.

Its contract is:

```text
CORTEX
  -> RuntimePolicy authorization
  -> Medusa planning
  -> validated specialist execution
  -> response assembly
```

Current Medusa work focuses on:

- capability-aware specialist selection
- authorized execution plans
- deterministic planning
- dependency-aware execution
- concurrency-safe execution budgets
- lifecycle and health handling
- least-privilege tool/plugin access
- safe errors and execution provenance

### LangGraph

LangGraph is reserved for real graph workflows:

- multi-step plans
- branching execution
- checkpoint/resume
- human-in-the-loop approval
- long-running graph state
- tool chains requiring graph semantics

It is not the default chat runtime and should not duplicate CORTEX or ChatRuntime authority.

## Memory

Karen separates memory responsibilities instead of treating memory as one giant service.

- **STM**: recent conversation/session state
- **Episodic**: meaningful interactions and decisions
- **LTM**: durable facts and preferences
- **NeuroRecall**: retrieval strategy, ranking, and recall signals
- **NeuroVault**: governed persistence, recovery, archive, and deletion semantics

The target persistence stack includes PostgreSQL, Redis, Milvus, and Elasticsearch where appropriate. Memory access must remain tenant-aware and auditable.

## Extensions / Plugins

The extension subsystem is being consolidated into one canonical governed runtime.

The target execution path is:

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

The legacy root-level plugin loader and placeholder Medusa extension dispatch are transitional code and are being replaced by the canonical extension kernel.

Extensions must declare:

- identity and version
- capabilities
- permissions
- input/output contracts
- prompt contracts when AI-backed
- side-effect requirements
- tenant/RBAC requirements
- dependency and health requirements

Manifest declaration is **not** authorization. Runtime policy remains the authority.

## Security

Security responsibilities include:

- authentication
- RBAC
- tenant isolation
- session validation
- secret handling and redaction
- action authorization
- audit logs
- extension permission checks
- safe error translation

Frontend checks are presentation only. Privileged behavior must be enforced on the backend.

## Observability

The target runtime metadata includes:

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

Prometheus is the canonical numeric metrics backend. Grafana is optional through the observability Compose profile.

## Repository Layout

The repository is actively being normalized. Canonical application code lives under `src/`.

```text
AI-Karen/
├── src/
│   ├── ai_karen_engine/
│   │   ├── core/
│   │   │   ├── cortex/
│   │   │   ├── runtime/
│   │   │   ├── model_runtime/
│   │   │   ├── reasoning/
│   │   │   ├── memory/
│   │   │   ├── neuro_recall/
│   │   │   ├── neuro_vault/
│   │   │   ├── observability/
│   │   │   └── security/
│   │   ├── agent_medusa/
│   │   ├── config/
│   │   ├── integrations/
│   │   └── server/
│   └── ui_launchers/
│       └── Karen-AI-Theme/
├── tests/
├── docs/
├── scripts/
├── docker/
├── config_assets/
├── supabase/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

> The root-level `server/` tree is legacy/transitional and is being audited against `src/ai_karen_engine/server/`. Canonical server ownership belongs under `src/ai_karen_engine/server/`.

## Quick Start

### Requirements

- Python 3.10+
- Docker with Docker Compose
- Optional NVIDIA GPU for CUDA/vLLM workflows

### Clone

```bash
git clone https://github.com/agustealo/AI-Karen.git
cd AI-Karen
cp .env.example .env
```

Review the environment file before startup. Do not commit real credentials.

### Docker

Start the core stack:

```bash
docker compose up
```

Optional observability:

```bash
docker compose --profile observability up
```

Optional Ollama service:

```bash
docker compose --profile ollama up -d ollama
```

Optional GPU-backed vLLM:

```bash
docker compose --profile vllm up -d vllm
```

CPU overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up
```

### First Run & Login

After the services are running, complete the initial administrator setup before using protected parts of Karen.

### 1. Confirm the API is running

Open:

```text
http://localhost:8000/docs
```

or check the authentication service:

```bash
curl http://localhost:8000/api/auth/status
```

### 2. Check whether first-run setup is required

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

### 3. Create the first administrator

The canonical setup path is:

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

This creates the initial user with `admin` and `user` roles and returns an authenticated session. The initial username is derived from the email prefix, so `you@example.com` becomes `you`.

### 4. Open the web interface

Visit:

```text
http://localhost:8010
```

Log in with either the email used during first-run setup or the generated username, plus the password you created.

### 5. API login

The canonical login endpoint is:

```text
POST /api/auth/login
```

Email example:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "your-password"
  }'
```

Username login is also supported:

```json
{
  "username": "you",
  "password": "your-password"
}
```

Successful login returns an access token, refresh token, user information, and resolved RBAC permissions. The backend also sets the canonical `kari_session` HTTP-only cookie for browser sessions.

### Legacy development admin helper

The repository currently still contains `create_admin.py`, which creates or updates this development account:

```text
Email:    admin@kari.ai
Username: admin
Password: Admin@123!
```

This is **legacy development/bootstrap tooling**, not the recommended installation flow. It contains a hardcoded development credential and is scheduled for cleanup with the root-normalization work.

Prefer `/api/auth/first-run/setup` for new installations. Never use the legacy password in production.

### Development auth bypass

Development environments also support explicit auth bypass through configuration such as:

```text
ENVIRONMENT=development
AUTH_DEV_MODE=true
```

or the explicit `KARI_AUTH_BYPASS` switch. These are development/testing mechanisms only and must not be enabled in a real deployment.

### What to configure after login

A new installation should normally verify these next:

1. **Provider availability**: confirm at least one local or configured model provider is healthy.
2. **Model configuration**: configure the desired local/default model path.
3. **Memory services**: confirm persistence services if durable memory is enabled.
4. **Extensions**: enable only governed extensions required for the deployment.
5. **Observability**: optionally start Prometheus/Grafana with the `observability` profile.
6. **Secrets**: replace example JWT, database, Redis, provider, and Grafana credentials before production use.

## Default Development Endpoints

| Service | Address |
|---|---|
| Web UI | http://localhost:8010 |
| API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| Metrics | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |

Optional services are available only when their corresponding Compose profile is enabled.

## Local Provider Options

Karen can work with local and external model providers through the canonical model-runtime layer.

Common local options include:

- vLLM
- Hugging Face Transformers
- Ollama
- OpenAI-compatible local endpoints
- GGUF/local runtimes where enabled by current configuration

Provider availability is determined at runtime from backend configuration and health, not hardcoded in the UI.

## Configuration

Canonical configuration code lives in:

```text
src/ai_karen_engine/config/
```

Static configuration assets currently live in:

```text
config_assets/
```

Configuration should be loaded through the canonical config package. Application code should not directly open config files when a loader or settings contract already exists.

Environment variables are used for deployment-specific overrides and secrets.

## Development Rules

Before adding a new service, registry, orchestrator, helper, route, provider, or config path:

1. Find the current owner.
2. Search for an existing implementation.
3. Prefer extending the canonical implementation.
4. Remove duplicate or dead paths after migration.
5. Preserve RBAC, tenant isolation, audit, and telemetry.
6. Keep routes thin.
7. Keep provider/model decisions out of the UI.
8. Keep CORTEX decision-only.
9. Keep Runtime execution-authoritative.
10. Prove the change with tests.

## Verification

Core verification commands:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
```

Frontend verification should additionally run from the active UI package:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## Current Convergence Work

The project is actively closing several architectural seams:

- Medusa dependency-aware and least-privilege execution
- canonical extension/plugin kernel
- root-directory normalization and legacy server collapse
- CI exact-head verification
- provider/model authority consolidation
- legacy orchestrator removal
- config and runtime-state normalization

These are cleanup and authority-convergence tasks, not parallel replacement frameworks.

## Architecture Documentation

See:

- `src/ai_karen_engine/core/ARCHITECTURE.md` for the canonical authority matrix
- `src/ai_karen_engine/core/README.md` for core-domain ownership
- `src/ai_karen_engine/config/README.md` for configuration ownership
- `docs/` for subsystem and migration documentation

## License

See `LICENSE`, `LICENSE.md`, and `LICENSE-commercial.txt` for the repository's licensing terms.

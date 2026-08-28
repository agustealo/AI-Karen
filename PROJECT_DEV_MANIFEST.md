# AI KAREN Project Developer Manifest

> **Status:** canonical developer contract and architecture truth map
> **Applies to:** backend, runtime, AI/ML, agents, memory, extensions, APIs, UI, infrastructure, first-run/bootstrap, tests, and documentation
> **Live baseline:** refreshed from `main` at `f71dd27bc881598d728af2c75fbafc491f20c369` on 2026-08-28
> **Rule:** live code is implementation truth. This manifest defines ownership and target direction; historical sprint sheets and compatibility layers never override it.

AI KAREN is a **local-first, prompt-first, modular AI runtime** with governed execution, durable memory, provider/model orchestration, cognitive routing, multi-agent execution, RBAC, audit, extensibility, first-class bootstrap, and observable system behavior.

Libraries, model runtimes, workflow engines, research systems, and UI frameworks remain subordinate capabilities behind KAREN-owned contracts.

---

## 1. Engineering mission

Every major responsibility must have:

1. one owner;
2. one canonical contract;
3. one runtime path;
4. one registry/config source where applicable;
5. explicit tenant/security boundaries;
6. observable lifecycle events;
7. executable proof.

Core rules:

- **Local-first:** prefer healthy local capabilities when suitable.
- **Prompt-first:** prompts are explicit, versioned, testable execution contracts.
- **Runtime-authoritative:** routes, UI, providers, agents, plugins, and workflow engines do not become alternate runtimes.
- **CORTEX is central cognitive authority. CORTEX decides; Runtime executes.**
- **RuntimePolicy authorizes. CORTEX does not authorize itself.**
- **DRY by authority:** one responsibility -> one owner -> one path.
- **Typed and async-safe:** public runtime/cognitive boundaries are typed; cancellation, budgets, and concurrency are explicit.
- **Config-driven:** provider/model selection, endpoints, fallbacks, flags, security modes, budgets, and environment come from canonical config.
- **Honest degradation:** unavailable capability produces explicit degraded/unavailable state, never fabricated output.
- **Security-preserving:** RBAC, tenant isolation, session validation, audit, plugin permissions, and secret redaction are backend-enforced.
- **Test-proven:** architecture contracts and burn tests are part of the product, not optional documentation.

---

## 2. Canonical authority map

| Responsibility | Canonical owner | Must not own it |
|---|---|---|
| HTTP ingress | `src/ai_karen_engine/api_routes/` + app composition | provider choice, prompt assembly, recall, orchestration |
| Request lifecycle/execution | `core/runtime/` | routes, UI, CORTEX, agents |
| Cognitive decisions | `core/cortex/` | authorization, provider execution, persistence |
| Signal extraction / ML inference | `core/intelligence/` | final cognitive authority, execution, authorization |
| Cognitive vocabulary/state | `core/cognitive/` | global orchestration, provider execution |
| Runtime authorization | `core/runtime/policy/` | cognitive classification, provider execution |
| Prompt assembly | canonical runtime prompt layer | providers, routes, UI, agents |
| Reasoning | `core/reasoning/` | provider registry authority, durable memory authority |
| Provider/model runtime | canonical model runtime + provider registry | UI, routes, CORTEX |
| Memory recall strategy | NeuroRecall / canonical memory runtime | durable storage authority, tool execution |
| Memory formation | MemoryFormation + NeuroVault | CORTEX, recall, route code |
| Graph workflows | LangGraph only for true graph semantics | ordinary chat, duplicate global orchestration |
| Multi-agent execution | Agent Medusa | provider selection, global authorization |
| Extensions/actions | governed extension/action runtime | route-level execution, self-authorization |
| Configuration | `src/ai_karen_engine/config/` + deployment adapter | scattered direct environment reads, React fallbacks |
| Observability | canonical platform observability | shadow subsystem telemetry silos |
| First durable owner/tenant | canonical AuthService | UI flags, direct route SQL, legacy bootstrap helpers |
| First-run deployment proof | `scripts/ci/production-first-boot-smoke.sh` + workflow | mocked-only setup tests |

**CORTEX is the central cognitive authority, not the supreme system authority.** Security/policy, execution, persistence, provider routing, prompt assembly, observability, bootstrap identity, and configuration remain independent authorities in their domains.

---

## 3. Canonical runtime path

```text
Transport / API
      |
      v
ChatRuntime
      |
      v
RuntimeDecisionPipeline
      |
      +--> Intelligence signals
      +--> CORTEX cognitive decision
      +--> RuntimePolicy authorization
      |
      v
AuthorizedExecutionPlan
      |
      +--> governed memory recall
      +--> DIRECT -> PromptRuntime -> model runtime
      +--> REASONING -> ReasoningExecutor
      +--> WORKFLOW / MULTI-AGENT -> WorkflowRuntime / Medusa
      +--> tools / extensions through governed action execution
      +--> persistence / formation under policy
      +--> audit / telemetry / outcome
```

API routes normalize/validate/authenticate and delegate. They do not select providers, build prompts, perform recall, execute plugins, create fallback answers, or become orchestration engines.

---

## 4. First-run system: first-class bootstrap authority

First run is a governed lifecycle, not one API endpoint.

### 4.1 Canonical lifecycle

```text
validated production config
        |
        v
canonical schema migrations
        |
        v
API liveness + auth readiness
        |
        v
GET /api/auth/first-run
        |
        v
POST /api/auth/first-run/setup
        |
        +--> canonical AuthService creates first owner
        +--> durable tenant scope
        +--> backend RBAC resolution
        +--> authenticated HTTP-only session
        |
        v
first-run closes
        |
        v
restart exact production image
        |
        v
normal login + authenticated /me survives restart
        |
        v
optional providers/models/memory/extensions report independent readiness
```

### 4.2 Lifecycle states

- **BOOTSTRAP_BLOCKED:** required production config, DB, migrations, or auth readiness is unavailable. Fail honestly.
- **OWNER_REQUIRED:** platform is bootstrap-capable and no durable user exists.
- **OWNER_CREATED:** initial owner + tenant + RBAC/session exist durably.
- **OPERATIONAL:** owner survives restart and normal authentication works.

Provider/model availability is not allowed to redefine auth first-run truth. A securely initialized installation may be degraded because no model provider is healthy. That state belongs to runtime/model readiness, not administrator recreation.

### 4.3 First-run ownership rules

- `GET /api/auth/first-run` answers only whether durable auth bootstrap is required.
- `POST /api/auth/first-run/setup` delegates creation/authentication to canonical `AuthService`.
- The route may not choose/download models, select providers, mutate memory, execute extensions, run migrations, or perform direct SQL bootstrap.
- Schema lifecycle belongs to canonical migrations.
- Tenant scope is durable backend truth, never a UI default.
- RBAC is backend-resolved.
- A second bootstrap attempt must not create another initial owner.
- Restart must not reopen first-run state.

### 4.4 Production security invariants

Production first run must prove:

```text
ENVIRONMENT=production
DEBUG=false
AUTH_DEV_MODE=false
AUTH_ALLOW_DEV_LOGIN=false
KARI_AUTH_BYPASS=false
AUTH_ENABLE_SESSION_VALIDATION=true
AUTH_AUTO_CREATE_TABLES=false
```

Additionally:

- deployment secrets are supplied explicitly;
- first-run responses do not expose secrets;
- durable owner receives non-empty tenant scope;
- RBAC permissions come from backend authority;
- session cookie is HTTP-only;
- migrations, not route-level DDL, own schema;
- dev bootstrap helpers/hard-coded credentials are not production installation paths.

### 4.5 First-run proof owners

Canonical documentation:

`docs/architecture/FIRST_RUN_SYSTEM.md`

Static architecture guard:

```bash
python scripts/ci/validate_first_run_contract.py
```

Real production proof:

```bash
bash -n scripts/ci/production-first-boot-smoke.sh
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:first-run .
KAREN_SMOKE_API_IMAGE=ai-karen-api:first-run \
  bash scripts/ci/production-first-boot-smoke.sh
```

CI owner:

`.github/workflows/production-first-boot-smoke.yml`

The smoke uses an isolated Docker network, a fresh PostgreSQL database, password-protected Redis, canonical migrations, production-safe auth flags, first-owner creation, authenticated `/me`, API restart, and durable login after restart.

---

## 5. Provider/model runtime

Provider/model authority must stay centralized.

Fallback behavior is config/policy-driven and honest. Conceptually:

```text
requested provider/model
  -> local primary
  -> configured local engines
  -> Ollama/OpenAI-compatible local endpoint when healthy
  -> configured external provider when enabled
  -> explicit unavailable/degraded result
```

No route, UI component, agent, first-run workflow, or plugin may invent provider availability or manufacture fallback model output.

Runtime/degradation metadata should include requested/actual provider/model, runtime engine, fallback level, degradation reason, response source, latency, and correlation identity.

---

## 6. Prompt-first contract

Prompt assembly belongs to canonical runtime prompt authority.

Prompts must be explicit, versioned, testable, and linked to execution intent. Assembly must respect system policy, persona/profile, tenant scope, governed memory/evidence, tool contracts, provider capability, token budget, safety, and requested output format.

Providers and routes do not independently reconstruct prompts.

---

## 7. Memory contract

Keep memory roles distinct:

- **STM:** recent session/conversation state, bounded/cache-oriented.
- **Episodic:** meaningful interactions and decisions.
- **LTM:** durable facts/preferences.
- **NeuroRecall:** retrieval strategy/scoring, not a duplicate store.
- **MemoryFormation:** post-outcome decision about durable learning candidates.
- **NeuroVault:** governed durable mutation, deletion, backup/recovery semantics.

Rules:

- tenant isolation is explicit and fail-closed;
- retrieval provenance/confidence/temporal state is preserved;
- failed recall must not automatically suppress an independently authorized formation event;
- durable writes do not bypass canonical formation/vault authority;
- no UI may claim memory was saved before backend persistence succeeds.

---

## 8. Agents and graph workflows

### Agent Medusa

Medusa is a specialist execution topology, not a second runtime or policy engine.

```text
CORTEX decision
  -> RuntimePolicy authorization
  -> Medusa planning
  -> validated specialist execution
  -> response assembly
```

Distributed execution must preserve tenant/request identity, fenced ownership, cancellation ownership, heartbeats/orphan semantics, and observable run state.

### LangGraph

Use LangGraph only for genuine graph semantics such as branching, checkpoint/resume, long-running state, human approval, or multi-step tool chains. Ordinary chat stays on the canonical runtime path.

---

## 9. Extensions/actions

Canonical governed path:

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

A manifest declaration is not authorization. Extensions declare capabilities/permissions/contracts; RuntimePolicy and action gates decide whether execution is allowed for the active user/tenant/context.

---

## 10. Configuration

Canonical configuration lives under:

`src/ai_karen_engine/config/`

Every meaningful option should have:

- default behavior;
- environment override where appropriate;
- validation;
- documentation;
- safe failure semantics.

Do not scatter provider names, model IDs, ports, URLs, feature flags, plugin paths, fallback order, or security modes across routes/UI/subsystems.

First-run production configuration must fail safe. Convenience development switches remain development-only and must never be silently promoted to production bootstrap behavior.

---

## 11. Security

Enforce:

- authentication/session validation;
- RBAC;
- tenant isolation;
- action authorization;
- extension permissions/manifests;
- secret redaction;
- audit logging;
- safe errors;
- correlation/request identity.

Forbidden:

- UI-only security;
- cross-tenant recall;
- plugin execution without policy/permission validation;
- admin actions without audit;
- fallback paths that bypass policy;
- first-run paths that enable dev authentication or auto-create production schema.

When deleting/moving code, migrate security guards to the canonical owner before removing the old path.

---

## 12. Observability

Every important runtime path should be traceable with fields such as:

```text
correlation_id
request_id
user_id
tenant_id
session_id
conversation_id
intent
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
error_type
error_code
```

First-run/bootstrap should additionally make failure location obvious: config, migration, dependency readiness, auth bootstrap, session/RBAC, restart persistence, or post-setup capability readiness.

Use structured logging and canonical metrics. Do not introduce subsystem-specific shadow telemetry when the platform observability path can own the signal.

---

## 13. DRY / legacy cleanup

Classify existing code as:

- active/correct;
- misplaced;
- useful/incomplete;
- replaced/dead;
- compatibility shim;
- experimental/feature-flagged;
- dangerous.

Before deleting:

1. identify purpose;
2. search imports/references;
3. inspect tests/docs/config/UI/runtime/plugins;
4. confirm canonical replacement;
5. migrate required security/telemetry behavior;
6. delete dead path;
7. prove no stale references remain.

Never keep dead code "just in case". Never delete migrations, auth/RBAC/audit/security/recovery or memory schemas without explicit replacement proof.

---

## 14. Testing and proof

Core commands:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
docker compose config
python scripts/ci/validate_first_run_contract.py
```

Frontend package:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm test
npm run build
```

First-run production proof:

```bash
bash -n scripts/ci/production-first-boot-smoke.sh
```

Every architecture cut should include the narrow proof for the changed authority plus the relevant broader gate. A green unrelated smoke does not prove the changed subsystem.

---

## 15. Current convergence priorities

1. **Classifier/CORTEX convergence:** collapse competing intent vocabularies/surfaces behind one canonical CORTEX decision envelope while keeping Intelligence as a signal producer.
2. **Evidence-informed cognition:** carry richer typed cognitive/evidence context through decision and prompt assembly without moving authorization into CORTEX.
3. **Memory lifecycle closure:** preserve provenance/calibration, decouple recall from formation eligibility, evaluate durable formation after actual outcomes.
4. **Provider/model authority:** keep all provider availability, selection, fallback, and runtime truth centralized and config-driven.
5. **Extension governance:** one manifest/registry/lifecycle/action execution path with RBAC and audit.
6. **First-run productization:** keep the new first-run architecture contract and real production smoke green as auth/config/migrations/runtime evolve.
7. **Legacy/root normalization:** collapse misleading compatibility accessors and duplicated roots only after reference audits.
8. **CI exact-head proof:** architecture/burn gates must attest and test the exact commit being promoted.

---

## 16. First-run definition of done

A KAREN release does **not** have a first-class first-run system unless all are true:

- [ ] production config validates without insecure implicit defaults;
- [ ] canonical migrations initialize an empty database;
- [ ] API liveness and auth readiness succeed;
- [ ] empty install reports `first_run_required=true`;
- [ ] first owner is created only through canonical AuthService authority;
- [ ] owner has durable tenant scope;
- [ ] backend RBAC permissions resolve;
- [ ] authenticated HTTP-only session is issued;
- [ ] subsequent first-run status is false;
- [ ] bootstrap cannot be replayed to create another initial owner;
- [ ] API process restart preserves owner/bootstrap state;
- [ ] normal login succeeds after restart;
- [ ] optional model/memory/extension failures remain explicit independent degraded states;
- [ ] architecture validator passes;
- [ ] real production first-boot smoke passes on the exact candidate SHA;
- [ ] README and this manifest match the executable contract.

---

## Final command

Protect architecture. Use the existing source of truth. Collapse duplicates. Delete dead code. Keep routes thin, Runtime authoritative, CORTEX decision-only, RuntimePolicy authoritative for authorization, providers registered, memory layered, extensions governed, first-run secure and durable, UI honest, telemetry complete, and tests as proof.

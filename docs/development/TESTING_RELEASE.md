# Testing and Release Proof

## 1. Principle

A change is not complete because it compiles locally or looks correct in code review. KAREN treats tests as executable architecture proof.

## 2. Baseline backend proof

Run the relevant subset, and for broad/core changes run the full set:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Do not report success unless the command/status was actually observed.

## 3. Frontend proof

Use the repository's configured package manager/scripts for the equivalents of:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

UI/API contract changes require both backend and frontend proof.

## 4. Infrastructure proof

For Compose/deployment changes:

```bash
docker compose config
```

Image/build changes should additionally prove the canonical ASGI target, healthcheck, required write paths, runtime user permissions, and immutable build behavior when applicable.

## 5. Architecture tests

High-risk ownership rules should be encoded in `tests/architecture/`.

Examples:

- retired files do not reappear;
- routes do not own provider selection;
- CORTEX has no provider/platform execution authority;
- only canonical health/readiness routes exist;
- only canonical metrics authority exists;
- legacy memory/provider runtimes remain retired;
- canonical app target is preserved;
- extension/action execution uses the governed gate;
- compatibility shims remain logic-free.

## 6. Provider/model tests

Prove:

- requested provider/model handling;
- provider health/availability;
- local-first routing;
- configured fallback order;
- actual provider/model metadata;
- unavailable/degraded behavior;
- no fake model output;
- OpenAI-compatible local endpoints including vLLM configurations.

## 7. Prompt tests

Prove:

- prompt version selection;
- deterministic assembly/hash semantics;
- precedence rules;
- token-budget behavior;
- memory/context truncation integrity;
- output contract/schema handling;
- allowed overrides;
- provider capability adaptation without provider-owned prompt authority.

## 8. Memory tests

Prove:

- message persistence when enabled;
- episodic/LTM write eligibility;
- tenant/user isolation;
- recall ranking/scoping;
- deletion/forget behavior;
- restart durability;
- truthful persistence failure handling;
- no retired Milvus/Elasticsearch dependency.

## 9. Security tests

Prove:

- production auth bypass is impossible/disabled;
- session validation;
- tenant isolation;
- RBAC policy dominance;
- plugin/action permission denial;
- admin action protection/audit;
- secret redaction;
- safe errors;
- no cross-tenant recall/action execution.

## 10. Agent/reasoning/graph tests

Prove:

- reasoning contracts/types;
- verification/evidence authority;
- runtime-injected generation clients;
- graph state/node determinism where required;
- LangGraph is not mandatory for simple chat;
- Medusa definition validation;
- budgets/parallelism/depth limits;
- subagent permission failure is fail-closed;
- cancellation/failure/trajectory semantics.

## 11. API tests

Prove:

- request/response schema;
- authentication/tenant context;
- error translation;
- thin-route delegation;
- health/liveness/readiness contracts;
- metrics scrape security;
- admin separation;
- no duplicate routes with divergent response truth.

## 12. Deletion proof

Before deleting a file/module:

```text
purpose identified
references searched
replacement verified
security guards accounted for
imports migrated
tests updated
stale docs/config searched
architecture guard added when useful
```

## 13. Beta/release gates

A public beta/release candidate should prove at minimum:

- first-run/bootstrap flow;
- secure authentication/session flow;
- first real chat response;
- local/provider runtime response truth;
- degraded/unavailable behavior;
- persistence across restart where promised;
- health/readiness behavior;
- major RBAC/admin boundaries;
- extension/plugin governance;
- no fake save/success/model states;
- clean production configuration validation;
- build/start from a clean environment.

## 14. CI interpretation

GitHub commit status with no checks is **not green CI**. Distinguish:

- tests run locally and passed;
- specific CI checks passed;
- CI pending;
- no CI status available;
- release gate closed/not closed.

Never collapse those into one optimistic "green" statement.

## 15. Release artifacts

Production direction:

- build once in CI;
- immutable image tag/digest;
- SBOM/provenance where supported;
- secrets supplied at runtime or secure build-secret mounts, never baked into image/build args;
- database migrations run through a governed migration/CI path, not automatically on API startup;
- `/health/live` for process liveness;
- `/ready` for traffic readiness.

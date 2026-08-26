# Repository and Engineering Methodology

## 1. Default development method

Before changing code:

1. identify the current owner;
2. search for duplicates and stronger implementations;
3. classify touched code;
4. decide whether to extend, merge, move, shim, flag, or delete;
5. preserve security/tenant/audit/telemetry behavior;
6. define proof before implementation.

## 2. Search before adding

Do not add a new service/helper/registry/folder until live repository search proves the responsibility has no appropriate existing owner.

Prefer:

```text
extend canonical owner
 > merge duplicate into canonical owner
 > add adapter/port where boundary is real
 > create a new subsystem only when responsibility is genuinely new
```

## 3. Code classification

Use these labels during cleanup:

- **active/correct**: canonical or correctly placed;
- **misplaced**: useful logic under wrong owner;
- **useful/incomplete**: preserve and finish/extract;
- **compatibility shim**: temporary bridge with explicit replacement/removal condition;
- **experimental**: isolated behind a feature flag;
- **replaced/dead**: remove after reference audit;
- **dangerous**: disable/replace while preserving required guards.

## 4. File/folder rules

Canonical application code belongs under `src/ai_karen_engine/`.

Root-level implementation packages are migration debt unless explicitly documented as infrastructure/configuration roots.

Avoid generic dumping grounds such as `utils`, `helpers`, or `services` when a domain owner exists. A utility shared across domains must be truly generic and free of domain authority.

Keep APIs grouped by domain under `api_routes/`. Keep platform concerns under platform/config/security/observability owners rather than inside route modules.

## 5. Module design

- one module should have a coherent reason to change;
- prefer typed dataclasses/Pydantic/domain contracts for public boundaries;
- use classes when lifecycle/state/polymorphism genuinely benefits from them, not mechanically;
- use functions for focused stateless operations;
- make dependencies explicit;
- avoid module-global request/user/tenant state;
- side effects should be visible in names/contracts;
- async tasks require clear owner, timeout, cancellation, and shutdown semantics.

## 6. DRY means authority, not just fewer lines

Duplicated code is harmful, but duplicated **authority** is worse.

Examples of authority duplication:

- two provider registries;
- two prompt assemblers;
- two memory stores/facades;
- route and runtime both selecting models;
- LangGraph and Medusa both acting as global orchestrator;
- two health systems;
- two Prometheus registries;
- UI and backend both inventing model availability.

Collapse the authority even when some adapter code remains duplicated temporarily.

## 7. Configuration

Configuration belongs under `src/ai_karen_engine/config/`, environment variables, and validated runtime settings.

Do not hardcode:

- providers/models;
- fallback order;
- ports/URLs;
- feature flags;
- DB paths/DSNs;
- plugin directories;
- security modes;
- deployment environment behavior.

Every durable config option should have a default when safe, environment override, validation, documentation, and safe failure behavior.

## 8. Error handling

- catch exceptions at the layer that can actually handle them;
- preserve error categories/reason codes;
- do not swallow exceptions into empty/fake-success responses unless the contract explicitly defines an optional best-effort result;
- avoid broad `except Exception` around core authority paths without structured handling;
- do not expose secrets or internal stack data to clients.

## 9. Logging

Use canonical structured logging and correlation context. No runtime `print()` statements. Prefer parameterized logging to f-string logs in frequently executed runtime paths.

## 10. Documentation

Architecture-changing code must update the relevant canonical doc. Historical sprint/closure docs should be marked historical or moved to a historical area rather than competing with current documentation.

Documentation must never claim a dependency/store/runtime is current if live code has retired it.

## 11. Deleting code

Before deletion:

1. identify purpose;
2. search imports/references;
3. inspect tests/docs/config/UI/runtime/plugins;
4. identify canonical replacement or prove dead;
5. preserve security/audit/RBAC behavior;
6. migrate consumers;
7. delete;
8. add a regression/reference guard when resurrection is risky.

Do not delete migrations, production configuration, auth/RBAC/audit logic, memory schemas, or recovery tools without explicit verification.

## 12. Review standard

A review should ask:

- does this introduce a second owner?
- is provider/platform authority leaking into Core cognition?
- are routes still thin?
- does UI display backend truth?
- are memory scopes explicit?
- are permissions enforced at execution time?
- are fallback/degraded semantics honest?
- is telemetry complete but cardinality-safe?
- what proves the architecture remains intact?

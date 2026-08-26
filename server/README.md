# Transitional Server Package

`server/` is a migration namespace, not a long-term application authority.

The canonical ASGI entrypoint is:

```text
ai_karen_engine.app:create_app
```

Docker, local launchers, production launchers, tests, and future deployment adapters must target that entrypoint rather than importing `server.app` directly.

## Ownership Rules

The root `server/` package may temporarily contain compatibility and composition helpers while responsibilities move to their canonical owners. No new runtime, provider, prompt, memory, agent, extension, auth-policy, persistence, startup-lifecycle, or observability authority may be added here.

### Application composition

- `server/app.py`: TRANSITIONAL. Health/readiness and startup-lifecycle ownership have been removed. It imports `create_lifespan` directly from `ai_karen_engine.server.startup`. Remaining composition responsibilities should continue moving into `src/ai_karen_engine/app.py` plus canonical API/platform helpers.
- `server/startup.py`: DELETED. It must not reappear. Root-server startup callbacks, provider/model warmup policy, memory initialization, extension recovery, and fallback ownership are retired.
- `src/ai_karen_engine/server/startup.py`: CURRENT canonical lifespan/bootstrap seam. It composes subsystem owners and remains a migration target for any behavior that still belongs deeper in runtime, database, memory, extensions, or observability.
- `server/routers.py`: TRANSITIONAL. Target owner: thin API route registration under `src/ai_karen_engine/api_routes/` / application composition.
- `server/middleware.py`: TRANSITIONAL. Target owner: canonical API/platform middleware.
- `server/validation.py`: REVIEW/MERGE. Validation belongs with the contract/config/security owner that defines the validated concern.
- `server/performance.py`: REVIEW/MERGE. Runtime tuning belongs in centralized configuration/runtime policy, not a second server policy layer.

### Configuration

- `server/config.py`, `server/config/`, `server/config.json`: TRANSITIONAL. Target owner: `src/ai_karen_engine/config/`.
- New environment/config options must be added to canonical config first, with defaults, validation, docs, and safe failure.

### Security / auth

- `server/security.py`: TRANSITIONAL. Target owner: canonical auth/security contracts and dependencies.
- Server helpers must not create a second RBAC, session, tenant, credential, or secret-policy implementation.

### Observability / health

- `server/metrics.py`: TRANSITIONAL. Target owner: `platform/observability/`. Preserve current callers while migrating; do not recreate a Core metrics authority.
- `server/health_endpoints.py`: DELETED. It must not reappear.
- `server/app.py`: owns no `/health` or `/api/health/*` routes.
- Connectivity/liveness/readiness authority: `src/ai_karen_engine/api_routes/monitoring/probes.py`.
- Detailed health/degraded-mode authority: `src/ai_karen_engine/api_routes/monitoring/health.py`.
- `server/enhanced_database_health_monitor.py`: REVIEW/MERGE. Database-health implementation belongs with the canonical database/platform owner.
- `server/extension_health_monitor.py`: REVIEW/MERGE. Extension health belongs with governed extension/platform observability seams.

### Database

- `server/database_config.py`: TRANSITIONAL. Supabase migrations are the schema authority. Runtime database connectivity/config belongs to the canonical database/platform adapter, not application startup DDL.
- Database startup/shutdown sequencing must be owned by canonical lifespan/database lifecycle, not root-server event callbacks.

### Admin API

- `server/admin_endpoints.py`: TRANSITIONAL. Target owner: dedicated admin API routes with backend RBAC/audit enforcement.

### Extension-era helpers

Files prefixed with `extension_` are migration debt unless a live reference audit proves a current governed role. Useful behavior must converge into `src/ai_karen_engine/extensions/`, canonical config, auth, or platform observability before the old file is removed.

### Deployment

- `server/deployment/`: REVIEW. Deployment is an operator/platform concern. Application runtime code must not depend on this directory.

## Removal Contract

Before deleting or moving any remaining file:

1. Identify current purpose and live callers.
2. Confirm the canonical replacement owner exists.
3. Preserve RBAC, tenant isolation, audit, secret handling, persistence, and telemetry behavior.
4. Update imports/tests/docs/config.
5. Delete the old file after the reference census is clean.
6. Add or update an architecture guard so the retired authority cannot silently reappear.

## Current Production Boundary

```text
Docker / CLI / service manager
        |
        v
ai_karen_engine.app:create_app
        |
        v
transitional server composition helpers
        |
        v
canonical FastAPI lifespan
        |
        v
Runtime / Database / Memory / Extensions / Observability owners
```

The migration is complete only when the remaining transitional server composition layer disappears without changing the public application entrypoint.

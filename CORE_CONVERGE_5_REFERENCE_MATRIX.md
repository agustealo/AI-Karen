# Reference Matrix: core/gateway & core/operations

Generated during CORE-CONVERGE-5 audit. Updated after migration pass.

## Summary

| Directory | Status | Action taken |
|-----------|--------|--------------|
| `core/gateway/` | Deleted | Entire package removed — zero external references |
| `core/operations/` | Partially migrated | Dead files deleted; legacy-active files migrated; metrics_manager moved to observability |

---

## Deleted files (zero external references)

| File | Reason |
|------|--------|
| `core/gateway/__init__.py` | Duplicate app factory package |
| `core/gateway/app.py` | Duplicate FastAPI app factory (`KarenApp`, `create_app`) |
| `core/gateway/middleware.py` | Duplicate middleware configuration |
| `core/gateway/routing.py` | Duplicate routing bootstrap |
| `core/gateway/communication_manager.py` | Legacy agent runtime, structurally broken |
| `core/operations/plugin_metrics.py` | Dead — no external imports |
| `core/operations/migration_tools.py` | Dead — no external imports |
| `core/operations/provider_metrics.py` | Dead — no external imports |
| `core/operations/health_checker.py` | Migrated callers to `ProviderRegistryService` |
| `core/operations/health_monitor.py` | Removed `core/services/dependencies.py` dependency |
| `core/operations/routing_decision_persistence.py` | Migrated `llm_router_service.py` to in-memory only |

---

## Migrated files

| File | Migration target | Callers updated |
|------|-----------------|-----------------|
| `core/operations/metrics_manager.py` | `core/observability/metrics.py` (canonical) | `server/metrics.py`, `auth/auth_middleware.py`, `services/streaming/stream_processor.py`, `api_routes/chat/runtime.py`, `monitoring/*`, `core/observability/sinks/metrics.py` |
| `core/model_runtime/model_selection_algorithm.py` | Uses `ProviderRegistryService` directly | `orchestration_agent.py`, `production_decision_service.py` |
| `services/orchestration/orchestration_agent.py` | Removed `HealthChecker` parameter | — |
| `core/model_runtime/production_decision_service.py` | Removed `HealthChecker` parameter | — |
| `services/models/routing/llm_router_service.py` | In-memory audit trail only | — |
| `core/observability/sinks/metrics.py` | Fixed API to match `MetricsManager` | — |
| `server/admin_endpoints.py` | Fixed broken import path | — |

---

## Remaining legacy-active files (pending future migration)

| File | Callers | Notes |
|------|---------|-------|
| `core/operations/performance_metrics.py` | `server/optimized_startup.py`, `api_routes/monitoring/performance.py` | Large duplicate observability platform; requires substantial refactor |

---

## Production entrypoint confirmation

- `start.py:19` → `from server.app import create_app`
- `docker-compose.yml:684` → `uvicorn server.app:create_app`
- `docker-compose-copilot.yml:308` → `uvicorn server.app:create_app`

No production code references `core/gateway`.

---

## Test impact

- All observability tests pass (19 passed)
- All metrics tests pass (10 passed)
- `test_fastapi_database_integration.py` failure is pre-existing (unrelated database config mock issue)

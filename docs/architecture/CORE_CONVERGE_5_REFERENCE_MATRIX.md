# Reference Matrix: core/gateway & core/operations

<<<<<<< HEAD
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

=======
Generated during CORE-CONVERGE-5 audit.

## Summary

| Directory | Dead refs | Legacy-active refs | Canonical-active refs | Verdict |
|-----------|-----------|-------------------|----------------------|---------|
| `core/gateway/` | 5/5 | 0 | 0 | Delete entire package |
| `core/operations/` | 2/9 | 5/9 | 1/9 (metrics_manager) | Migrate/merge, retire duplicates |

---

## A. `core/gateway` Reference Matrix

| Symbol | File | External refs | Classification | Notes |
|--------|------|---------------|----------------|-------|
| `create_app` | `app.py:130` | 0 | dead | Only referenced in `gateway/__init__.py` |
| `KarenApp` | `app.py:26` | 0 | dead | Only referenced in `gateway/__init__.py` |
| `setup_middleware` | `middleware.py:174` | 0 | dead | Only referenced in `gateway/__init__.py` and `gateway/app.py` |
| `setup_routing` | `routing.py:991` | 0 | dead | Only referenced in `gateway/__init__.py` and `gateway/app.py` |
| `CommunicationManager` | `communication_manager.py:95` | 0 | dead | No external imports; self-referential only |

### Gateway imports within package (internal only)
- `gateway/__init__.py` → imports from `app`, `middleware`, `routing`
- `gateway/app.py` → imports from `middleware`, `routing`
- No other files in the repo import from `ai_karen_engine.core.gateway`

### Production entrypoint
>>>>>>> 945781a4 (fix: replace fitz with pymupdf and update .gitignore)
- `start.py:19` → `from server.app import create_app`
- `docker-compose.yml:684` → `uvicorn server.app:create_app`
- `docker-compose-copilot.yml:308` → `uvicorn server.app:create_app`

<<<<<<< HEAD
No production code references `core/gateway`.
=======
**Conclusion:** `core/gateway` is a completely unused parallel app factory. No production code references it.

---

## B. `core/operations` Reference Matrix

| Symbol | File | External refs | Classification | Notes |
|--------|------|---------------|----------------|-------|
| `HealthChecker` | `health_checker.py:31` | 3 | legacy-active | `orchestration_agent.py`, `production_decision_service.py`, `model_selection_algorithm.py` (TYPE_CHECKING) |
| `HealthMonitor` | `health_monitor.py:93` | 1 | legacy-active | `core/services/dependencies.py` imports `get_health_monitor` |
| `get_metrics_manager` | `metrics_manager.py:228` | 8 | **canonical-active** | `server/metrics.py`, `auth_middleware.py`, `stream_processor.py`, `chat/runtime.py`, `monitoring/*`, `observability/sinks/metrics.py`, `provider_metrics.py` |
| `ProviderMetricsCollector` | `provider_metrics.py:118` | 0 | dead | No external imports; only self-referential |
| `record_plugin_call` | `plugin_metrics.py:29` | 0 | dead | No external imports |
| `RoutingDecisionPersistence` | `routing_decision_persistence.py:46` | 1 | legacy-active | `services/models/routing/llm_router_service.py` |
| `PerformanceMetrics` | `performance_metrics.py:1277` | 2 | legacy-active | `server/optimized_startup.py`, `api_routes/monitoring/performance.py` |
| `MigrationPlanner` / `DirectoryAnalyzer` | `migration_tools.py` | 0 | dead | No external imports |

### Detailed external reference list

#### `metrics_manager.py` (canonical-active, must migrate carefully)
1. `server/metrics.py:27` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
2. `server/admin_endpoints.py:232` → `from ai_karen_engine.core.metrics_manager import get_metrics_manager`
3. `src/ai_karen_engine/auth/auth_middleware.py:30` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
4. `src/ai_karen_engine/services/streaming/stream_processor.py:25` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
5. `src/ai_karen_engine/api_routes/chat/runtime.py:49` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
6. `src/ai_karen_engine/monitoring/validation_metrics.py:15` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
7. `src/ai_karen_engine/monitoring/model_orchestrator_metrics.py:15` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
8. `src/ai_karen_engine/monitoring/memory_metrics.py:10` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
9. `src/ai_karen_engine/core/observability/sinks/metrics.py:18` → `from ai_karen_engine.core.operations.metrics_manager import get_metrics_manager`
10. `src/ai_karen_engine/core/operations/provider_metrics.py:130` → `from ai_karen_engine.core.operations.metrics_manager import MetricsManager`

#### `health_checker.py` (legacy-active)
1. `src/ai_karen_engine/services/orchestration/orchestration_agent.py:19` → `from ai_karen_engine.core.operations.health_checker import HealthChecker`
2. `src/ai_karen_engine/core/model_runtime/production_decision_service.py:8` → `from ai_karen_engine.core.operations.health_checker import HealthChecker`
3. `src/ai_karen_engine/core/model_runtime/model_selection_algorithm.py:18` → `from ai_karen_engine.core.operations.health_checker import HealthChecker` (TYPE_CHECKING only)

#### `health_monitor.py` (legacy-active)
1. `src/ai_karen_engine/core/services/dependencies.py:21` → `from ai_karen_engine.core.operations.health_monitor import HealthMonitor, get_health_monitor`

#### `routing_decision_persistence.py` (legacy-active)
1. `src/ai_karen_engine/services/models/routing/llm_router_service.py:36` → `from ai_karen_engine.core.operations.routing_decision_persistence import RoutingDecisionPersistence, get_routing_persistence`

#### `performance_metrics.py` (legacy-active)
1. `src/ai_karen_engine/server/optimized_startup.py:23` → `from ai_karen_engine.core.operations.performance_metrics import PerformanceMetrics`
2. `src/ai_karen_engine/api_routes/monitoring/performance.py:19` → `from ai_karen_engine.core.operations.performance_metrics import get_performance_monitoring_system`

#### `provider_metrics.py` (dead)
- `FINAL_IMPLEMENTATION_SUMMARY.md:110` mentions it in documentation only
- `src/ai_karen_engine/core/operations/provider_metrics.py:130` imports `MetricsManager` internally
- No production code imports `ProviderMetricsCollector`, `record_provider_event`, etc.

#### `plugin_metrics.py` (dead)
- No external imports found

#### `migration_tools.py` (dead)
- No external imports found

---

## Deletion Gate Assessment

### Safe to delete immediately (zero external references)
- `core/gateway/` (entire package — 5 files)
- `core/operations/plugin_metrics.py`
- `core/operations/migration_tools.py`
- `core/operations/provider_metrics.py`

### Require migration before deletion
- `core/operations/health_checker.py` → migrate probes to provider health
- `core/operations/health_monitor.py` → merge into canonical health plane
- `core/operations/routing_decision_persistence.py` → migrate to ExecutionTrajectory
- `core/operations/performance_metrics.py` → extract regression detection, remove SQLite telemetry
- `core/operations/metrics_manager.py` → move under `core/observability/metrics` (keep temporarily as shim)

### Must NOT delete without migration
- None — all legacy-active files have clear migration paths
>>>>>>> 945781a4 (fix: replace fitz with pymupdf and update .gitignore)

---

## Test impact

<<<<<<< HEAD
- All observability tests pass (19 passed)
- All metrics tests pass (10 passed)
- `test_fastapi_database_integration.py` failure is pre-existing (unrelated database config mock issue)
=======
Tests that reference `create_app` from `server/app` (not `core.gateway`):
- `server/__tests__/test_fastapi_database_integration.py:13`
- `server/__tests__/test_integration_basic.py:255`

Tests referencing `metrics_manager`:
- `server/__tests__/test_metrics.py:29,58` (patches `metrics.get_metrics_manager`)

No tests import directly from `core.gateway`.
>>>>>>> 945781a4 (fix: replace fitz with pymupdf and update .gitignore)

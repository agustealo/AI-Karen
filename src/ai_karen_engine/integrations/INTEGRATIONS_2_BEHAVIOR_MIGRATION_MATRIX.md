# INTEGRATIONS-2: Provider & Routing Convergence — Behavior Migration Matrix

> Purpose: the safe, behavior-level map for retiring the surviving duplicate
> authority cluster in `src/ai_karen_engine/integrations/`. Per the audit rule,
> **no file is deleted until its last unique behavior is migrated to a canonical
> owner and proven.** This document is the source of truth for that migration.

Status: `live` = `2c04d5e7`. Canonical owners now exist in `core/`; the surviving
integrations files are the *dangerous* ones (large, intertwined, partially live).

---

## 1. Canonical owners (do not duplicate these)

| Concern | Canonical owner | Path |
|---|---|---|
| Provider registry (canonical) | `ProviderRegistryService` | `core/model_runtime/provider_registry_service.py` |
| Provider endpoints / model catalog | `ProviderEndpoint`, `BUILTIN_PROVIDER_ENDPOINTS` | `core/model_runtime/provider_endpoint.py` |
| Provider capability enum | `ProviderCapability` | `core/model_runtime/provider_registry_service.py` |
| Canonical health enum | `HealthStatus` (str Enum) | `core/model_runtime/provider_health_monitor.py` |
| Model catalog / discovery | `ModelDiscoveryService` | `core/model_runtime/model_discovery_service.py` |
| Model selection algorithm | `ModelSelectionAlgorithm` | `core/model_runtime/model_selection_algorithm.py` |
| Runtime resilience / fallback | `FallbackManager`, `get_fallback_manager` | `core/runtime/resilience/fallback_manager.py` |
| Runtime resilience health | `ResilienceHealthMonitor` | `core/runtime/resilience/health_monitor.py` |
| Provider selection / probing | `ProviderRouterProbe`, `ChatRuntimeControlPlane` | `core/runtime/chat_runtime_control_plane.py` |
| Authorization / capability gates | `RuntimePolicyEnforcer` | `core/runtime/policy/runtime_policy.py` |
| Task understanding | `IntelligenceRuntime` | `core/intelligence/intelligence_runtime.py` |
| Canonical prompts | `PromptRegistry` | `core/runtime/prompt/prompt_assembler.py` |
| Observability / metrics | `core/observability/*` (in progress) | — |

Live request path: `api_routes/chat/*` → `core.runtime.chat_runtime_service` →
`core.runtime.chat_runtime_control_plane` (canonical). Legacy top-level
`ai_karen_engine.llm_orchestrator` still binds to the integrations duplicate
`performance_adaptive_router` — it is **not** on the live path.

---

## 2. Provider-registry convergence (Task 1 / Task 2)

Rule: **ONE canonical provider registry, ONE canonical model catalog, ONE provider
selection owner.** `integrations/provider_registry.py` is the intentional bridge
(the canonical service subclasses it); `integrations/llm_registry.py` is the
active runtime state backing that bridge. The collapse target is to fold the
*unique* runtime behavior into `core/model_runtime` and delete the rest.

| File | Behavior | Canonical replacement | Consumers (external) | Status |
|---|---|---|---|---|
| `integrations/registry.py` | `LLMRegistry` (in-memory), dataclasses `ProviderSpec/RuntimeSpec/ModelMetadata/HealthStatus/...`, `get_registry()`, `get_available_providers`, `get_provider_with_routing` | `ProviderRegistryService` + `core/model_runtime/*` | `api_routes/models/{providers,management,intelligent_router,dynamic_provider}`, `inference/model_store.py`, `services/models/routing/intelligent_model_router.py`, `core/memory/profile_synthesis`, `integrations/{health_monitor,llm_router,confidence_scoring,dynamic_provider_system,llm_profile_system,failure_pattern_analyzer}` | **Migrate.** Split-brain with `llm_registry.py` — two `LLMRegistry` classes + two `get_registry()`. |
| `integrations/llm_registry.py` | `LLMRegistry` (JSON-backed, model entries + schema validation), `get_registry`, `get_provider`, `ProviderRegistration`, `ModelEntry` | `ProviderRegistryService` (wraps this today as base via `get_provider_registry`); long-term fold into `core/model_runtime/model_manager.py` | **41 consumers** incl. canonical `provider_registry_service.py:282` (lazy), `chat_runtime_control_plane.py:1427`, `neuro_recall/client/*`, `reasoning/{graph, synthesis, kro_orchestrator}`, `expression/engines/*`, `routing/*`, `services/*`, `capsules/*`, `config/*` | **This is the real runtime authority today.** Cannot be deleted until the canonical service owns provider state directly. |
| `integrations/provider_registry.py` | Legacy shim: `ProviderRegistry`, `ModelInfo`, `ProviderRegistration`, `get_provider_registry()` | Canonical: `core/model_runtime/provider_registry_service.py` | Canonical `provider_registry_service.py` (BASE class), `providers/{voice_registry,video_registry}.py`, `llm_orchestrator.py`, `api_routes/health/providers.py`, `__init__.py` (lazy) | **Keep as bridge for now.** It is the contract the canonical service subclasses. Collapse candidate once the service owns `ModelInfo`. |
| `integrations/intelligent_provider_registry.py` | `IntelligentProviderRegistry`, `ProviderType`, `ProviderPriority`, `IntelligentProviderRegistration`, `CapabilityMatcher` | `ProviderRegistryService` + `ProviderCapability` + `ModelSelectionAlgorithm` | `intelligent_provider_switcher.py`, `fallback_chain_manager.py`, `performance_adaptive_router.py`, `capability_aware_selector.py`, `model_availability_cache.py`, `monitoring/{comprehensive_health_monitor,health_based_decision_maker,test_comprehensive_health_monitor}` | **Isolated from canonical core** (no core import). Safe to retire once consumers migrate to `monitoring/comprehensive_health_monitor` + canonical. |
| `integrations/dynamic_provider_system.py` | `DynamicProviderManager`, `DynamicProviderSpec(ProviderSpec)` | `core/model_runtime/provider_registry_service.register_provider_endpoint` | `api_routes/models/{dynamic_provider,providers,management}`, `integrations/llm_profile_system.py` | **Wraps `registry.py`** (registers into its singleton). Parallel authority. |

### Migration order (provider registries)
1. Pick ONE canonical registry — **already done**: `core/model_runtime/provider_registry_service.py` (`ProviderRegistryService`).
2. Make `ProviderRegistryService` own provider state directly (stop lazily delegating to `llm_registry.get_registry` at line 282) — **behavior migration proof**: port `LLMRegistry.get_available_providers`/`get_provider_with_routing` semantics, add a test asserting the canonical service returns the same provider roster without touching `integrations.llm_registry`.
3. Migrate `api_routes/models/*` and `services/models/routing/*` off `integrations.{llm_registry,registry,dynamic_provider_system}.get_registry` onto `get_provider_registry_service()`.
4. Retire `integrations/intelligent_provider_registry.py` (consumers are the `monitoring/*` block + integrations routing cluster — both being retired).
5. Delete `registry.py`, then `llm_registry.py`, then downgrade `provider_registry.py` to a one-line re-export shim or delete.

### Blocking evidence
- `core/model_runtime/provider_registry_service.py:24` imports `ModelInfo`,
  `ProviderRegistration`, `get_provider_registry` from `integrations.provider_registry` — so the bridge must remain until `ModelInfo` is promoted to `core/model_runtime/runtime_provider_contracts.py` (canonical contract gap #1).

---

## 3. Routing authority convergence (Task 3)

Target chain: **IntelligenceRuntime → signals → CORTEX → execution requirements →
RuntimePolicy → allowed requirements → ProviderRouter → provider/model choice.**
Everything else feeds that path or disappears.

| File | Behavior | Canonical owner | Consumer evidence | Status |
|---|---|---|---|---|
| `integrations/llm_router.py` (2,798 ln) | provider scoring `IntelligentLLMRouter.score_provider` | `ProviderRouter` (`chat_runtime_control_plane.py`) | `api_routes/models/intelligent_router.py`, `services/error_response_service.py`, `services/models/routing/intelligent_model_router.py`, `confidence_scoring.py`, `routing_policies.py`, `capability_router.py` | **Mining target.** Retire after behavior extraction. |
| `llm_router.py` | privacy eligibility (`_get_most_restrictive_privacy_level`) | `RuntimePolicy` | (same) | extract → `RuntimePolicyEnforcer` |
| `llm_router.py` | task→provider mapping / task analysis (`RoutingRequest`, `TaskType`) | `IntelligenceRuntime` / CORTEX | (same) | overlaps `task_analyzer.py` |
| `llm_router.py` | fallback chain + retry (`route_with_fallback`, `_execute_fallback_chain`, `_*_selection_with_retry`) | `RuntimeResilience` | (same) | **move to `core/runtime/resilience`** |
| `llm_router.py` | Prometheus metrics (`_emit_*`) | Observability | (same) | route to `core/observability` |
| `integrations/capability_router.py` | capability fallback (`fallback_applied`), `get_capability_router` | `ProviderRouter` | only `llm_router.py` (lazy) | folded into llm_router retirement |
| `integrations/capability_aware_selector.py` | `CapabilityMatcher`, `get_capability_selector`, `SelectionStrategy` | `ModelSelectionAlgorithm` | `monitoring/comprehensive_health_monitor.py:35`, `health_based_decision_maker.py:32`, `test_comprehensive_health_monitor.py:22`, `intelligent_provider_switcher.py`, `fallback_chain_manager.py`, `performance_adaptive_router.py`, `model_availability_cache.py` | migrate `monitoring/*` → canonical monitor |
| `integrations/routing_policies.py` | `get_policy_manager`, `RoutingPolicy` | `RuntimePolicy` | `api_routes/models/intelligent_router.py:34` | consumer is a legacy router → co-retire |
| `integrations/performance_adaptive_router.py` | `PerformanceAdaptiveRouter`, `AdaptiveStrategy` | `ProviderRouter` + `RuntimePolicy` | legacy `llm_orchestrator.py:32,609` (NOT live path) | legacy — co-retire with orchestrator |
| `integrations/intelligent_provider_switcher.py` | `IntelligentProviderSwitcher` | `RuntimeResilience` + `ProviderRouter` | only `performance_adaptive_router.py` (lazy) | dead cluster w/ performance_adaptive_router |
| `integrations/provider_hierarchy.py` | `get_provider_hierarchy` | (delete) | **zero consumers** | **DELETED** (INTEGRATIONS-2) |
| `integrations/copilot_router.py` | `CopilotLLMRouter` | (delete) | **zero consumers** | **DELETED** (INTEGRATIONS-2) |
| `integrations/copilotkit_provider.py` | duplicate `CopilotKitProvider` | (delete) | **zero consumers** | **DELETED** (INTEGRATIONS-2) |

### Routing retirement proof (next)
After `provider_hierarchy`/`copilot_router`/duplicate `copilotkit_provider` are gone, the remaining routing cluster's only LIVE external consumers are `api_routes/models/intelligent_router.py` and `services/models/routing/{intelligent_model_router,llm_router_service}.py` and the legacy `llm_orchestrator.py`. Confirm these are not consulted by the live `ChatRuntimeControlPlane` path (they are not — control_plane uses `ProviderRouterProbe` + `get_registry`). That is the proof to retire `llm_router.py` + siblings.

---

## 4. Fallback-chain closure (Task 5)

Invariant: **adapters report failure → RuntimeResilience decides retry/fallback →
ProviderRouter chooses eligible alternatives.** Integrations must not invent its own
failover universe.

| File | Behavior | Canonical owner | Evidence | Status |
|---|---|---|---|---|
| `integrations/fallback_chain_manager.py` | `FallbackChainManager`, `FallbackChain`, `FallbackStep`, `ContextBridge`, `FallbackConfig`, `execute_fallback_chain` | `core/runtime/resilience/fallback_manager.py` + `ProviderRouterProbe` | `intelligent_provider_switcher.py`, `performance_adaptive_router.py` (both DUPLICATE) | **DEAD** per audit; collapse with the routing cluster above |
| embedded in `llm_router.py` | `route_with_fallback` (412), `_execute_fallback_chain` (739), `_*_with_retry` (619–855) | `RuntimeResilience` | only `llm_router` consumers | migrate w/ llm_router retirement |
| embedded in `capability_router.py` | `fallback_applied` flag (316/359) | `RuntimeResilience` | only `llm_router` | migrate w/ llm_router retirement |
| embedded in `registry.py` | `fallback_models`, `fallback_priority`, `can_fallback_to` (ProviderSpec) | canonical `ProviderEndpoint.fallback_eligible` | `registry.py` consumers | port model list to `core/model_runtime` |
| embedded in `llm_registry.py` | `default_chain` (1215), `"fallback"` provider (1592), `fallback_providers` (1797) | canonical fallback chains | `llm_registry` consumers | port |
| embedded in `performance_adaptive_router.py` | `_get_fallback_providers` (1089), `_on_fallback_switch` (1919) | `RuntimeResilience` | legacy orchestrator | co-retire |
| embedded in `health_monitor.py` | fallback-model iteration (567–586) | `core/runtime/resilience` | `llm_router` | migrate w/ health |
| `README_FALLBACK_CHAINS.md` | docs for retired `FallbackChainManager` API | (delete) | no code refs | **delete** |

### Collision to resolve
`FallbackChain` is defined in BOTH `integrations/fallback_chain_manager.py` (chain_id/steps/strategy) AND
`core/model_runtime/provider_registry_service.py:55` (primary/fallbacks/capability). The canonical one wins; remove the integrations dataclass.

### Closure proof (next)
Single test: route a synthetic provider failure through `core/runtime/resilience/FallbackManager` and assert `ProviderRouterProbe` returns an alternate provider — with zero calls into `integrations.fallback_chain_manager` or `llm_router.route_with_fallback`.

---

## 5. TaskAnalyzer retirement (Task 4)

`integrations/task_analyzer.py` is classified DUPLICATE. Its consumers are the routing/services layer, not integrations-internals:

| Consumer | Line | Usage | Verdict |
|---|---|---|---|
| `routing/kire_router.py` | 32, 80, 116 | `TaskAnalyzer`, `analyze`, `provider_supports` | **kire_router is legacy** (live path = `ChatRuntimeControlPlane`); confirm zero live-path callers before delete |
| `routing/actions.py` | 21, 63, 166 | `TaskAnalyzer()` | legacy predictor path |
| `routing/cognitive_reasoner.py` | 14 | `TaskAnalysis` import | legacy |
| `services/models/routing/enhanced_llm_router.py` | 59, 165, 224 | `TaskAnalyzer`, `TaskAnalysis`, `analyze_task` | **caller bug**: `analyze_task` not on `TaskAnalyzer` (only `analyze`) → dead call site |

### Retirement proof (next)
1. Confirm `ChatRuntimeControlPlane`/`IntelligenceRuntime` never call `TaskAnalyzer`/`analyze` (grep negative).
2. Note `enhanced_llm_router.py:224` calls a non-existent `analyze_task` → already dead.
3. Port any unique capability→KHRP-step mapping into `IntelligenceRuntime` versioned rules, then delete `task_analyzer.py`.

---

## 6. Model-lifecycle convergence (Task 6)

Compare `integrations/{model_availability_cache,model_availability_manager,model_discovery}.py`
against `core/model_runtime/*`.

| Integration file | Overlap vs core | Unique behavior | Canonical counterpart | Status |
|---|---|---|---|---|
| `integrations/model_discovery.py` | local scanning + list/get vs `model_discovery_service.py`; format inference vs `runtime_compatibility.py`; JSON write vs `model_registry_writer.py` | pluggable sources (`LocalModelSource/PluginModelSource`), `sync_registry()`, `REGISTRY_PATH` env | `core/model_runtime/model_discovery_service.py` | **consumer is `server/startup.py:249,379` only.** Port `sync_registry` to `model_registry_writer`, delete. |
| `integrations/model_availability_cache.py` | no public symbol overlap; conceptual w/ `model_registry_writer` (disk cache) + `model_validation` (integrity) | predictive preload, network-aware decisions, LRU weighted by RT/context, exponential-backoff download recovery | none (cache logic) | **consumers**: `monitoring/comprehensive_health_monitor` + the doomed routing cluster. Migrate cache reads to `core/model_runtime`, delete. |
| `integrations/model_availability_manager.py` | criteria selection vs `model_selection_algorithm.py`; `ModelFallbackRule` vs `provider_registry_service.FallbackChain` | model-level health checks, intra-provider fallback (gpt-4→gpt-3.5), request-type metrics, consecutive-failure tracking | `core/model_runtime/model_selection_algorithm.py` + `core/model_runtime/provider_registry_service.py` | **sole consumer is `llm_router.py`.** Delete with llm_router. |
| `integrations/registry.py` `ModelMetadata` | overlaps `core/model_runtime/model_registry_writer` shapes | ProviderSpec/RuntimeSpec dataclass set | promote to `core/model_runtime/runtime_provider_contracts.py` | port + delete |

### Collision to resolve
`FallbackChain` name collision (see §4). `ModelEntry` (`llm_registry`) vs canonical `core/model_runtime/model_manager` model list — unify on canonical.

---

## 7. Health decomposition (Task 7)

`integrations/health_monitor.py` is **125 KB / 2,792 lines** — ~77 methods in one
`ComprehensiveHealthMonitor`. Decompose by behavior, only AFTER consolidating to a
single canonical monitor (otherwise work is redone).

| Behavior bucket | Representative symbols (line) | Canonical owner | Action |
|---|---|---|---|
| Provider health / connectivity | `check_provider_health` (277), `test_provider_connectivity` (358), `_test_openai_capabilities` (834), `_test_*_capabilities`, `_test_api_key_validity` (1827) | `core/model_runtime/provider_health_monitor.py` | MOVE |
| Runtime health | `start_monitoring`/`stop_monitoring` (248/259), `_monitor_loop` (266), `_check_runtime_health` (1027) | `core/runtime/chat_runtime_control_plane.py` | MOVE |
| Availability | `verify_model_availability` (535), `get_healthy_components`/`get_unhealthy_components` (2592/2605), `get_best_alternative` (2713) | `core/model_runtime/provider_registry_service.get_available_providers` | MOVE |
| Metrics & rankings | `get_performance_metrics/analytics` (2161–2284), `record_request_metrics` (2301), `get_provider_rankings` (2284), `get_health_dashboard_data` (2065) | `core/observability` (canonical contracts §4) | MOVE |
| Failure history & failover | `HealthEvent` (160), `FailoverEvent` (174), `get_recent_events/failovers` (2651–2661), `_handle_status_change` (1413), `_attempt_failover` (1608) | `core/runtime/resilience` | MOVE |
| Recovery / degraded | `get_troubleshooting_suggestions` (2508), `reset_failure_count` (2702), callbacks (2479–2713) | `core/runtime/resilience` | MOVE |
| Dependency checks | `_get_provider_api_key`, `_find_model_path`, env/dep checks | `core/model_runtime/provider_policy.py` | MOVE |
| Caching & reporting | `_is_cache_valid` (1126), `get_system_diagnostics` (2356), `get_health_report` (2414) | `core/observability` + provider registry | MOVE |

### Decomposition proof (next)
The 125 KB file has **only two runtime consumers** (both in the doomed integrations cluster):
`integrations/llm_router.py` (12 call sites: 1324/1332/1981/1983/1984/2011/2012/2013/2014/2016) and
`integrations/confidence_scoring.py` (554/557/563 — injects a possibly-None monitor). The
canonical `monitoring/comprehensive_health_monitor.py` is consumed by the active
`monitoring/health_based_decision_maker.py`. **Plan:** migrate `confidence_scoring.py`
off the 125 KB monitor (use the canonical one or drop), then `llm_router` retirement
removes the last consumer → delete `integrations/health_monitor.py` and extract the
behavior buckets above into their canonical owners in small commits.

---

## 8. Completed this increment (INTEGRATIONS-2, part 1)

| Action | File(s) | Verification |
|---|---|---|
| Deleted dead CopilotKit duplicate adapter | `integrations/copilotkit_provider.py` (zero importers) | grep: 0 refs |
| Deleted dead CopilotKit duplicate router | `integrations/copilot_router.py` (zero importers) | grep: 0 refs |
| Deleted dead provider-hierarchy util | `integrations/provider_hierarchy.py` (zero importers) | grep: 0 refs |
| Deleted CopilotKit namespace shim | `integrations/copilotkit/` (`routing_actions.py`) | consumers migrated |
| Migrated consumers to canonical `routing.actions` | `api_routes/chat/copilot.py:782,893`, `integrations/startup.py:40` | direct import; behavior-identical (shim body was identical) |
| Fixed audit-test path bugs | `tests/test_integrations_authority_audit.py` (`INTEGRATIONS_ROOT` doubling; Windows `\` rel; dup-router `integrations/` prefix; deleted `integrations.llm.llm_registry` entry) | see §9 |
| Completed classification map (subdir packages) | `FILE_CLASSIFICATIONS` | `test_integrations_authority_audit_classifications` now green |

Real CopilotKit provider retained: `integrations/providers/copilotkit_provider.py`
(imports the real `copilotkit` SDK, wired into `providers/base.py` lazy map +
`config/llm_provider_config.py` + `provider_execution_resolver.py`). Real protocol
bridge retained: `ai_karen_engine/copilotkit/`.

---

## 9. Test status (environment note)

`pytest` was made runnable here via `uv` (Python 3.12). `rg` (ripgrep) is **not
installed** and the project dependency stack (`numpy`→`sqlalchemy`→...) cannot be
installed offline. Current run of
`tests/test_integrations_authority_audit.py`:

- **15 pass** — all path/file/classification/existence/routing-isolation tests,
  including `test_deleted_dead_files_are_gone`,
  `test_deleted_unused_subpackages_are_gone`,
  `test_integrations_authority_audit_classifications`,
  `test_no_duplicate_router_classes_outside_canonical_owners`,
  `test_integrations_init_exports_only_adapters`,
  `test_canonical_resilience_owns_fallback`,
  `test_core_runtime_does_not_import_from_duplicate_router_authorities`.
- **3 fail — all environmental, not caused by these changes:**
  `test_canonical_provider_registry_service_exists` and
  `test_canonical_provider_registry_service_is_single_source_of_truth` fail on
  `ModuleNotFoundError: numpy`/`sqlalchemy` imported transitively by
  `core/model_runtime/__init__.py` → `model_manager` → `embedding_manager`
  (untouched by this change). `test_duplicate_provider_registry_imports_are_documented`
  fails only because `rg` is absent (in a real env it passes — all 5 listed
  registries have live importers).

### Recommended follow-up with test execution available
1. Collapse the `registry.py` / `llm_registry.py` split-brain (§2) behind a
   behavior-equivalence test on the provider roster.
2. Retire `task_analyzer.py` after the live-path negative confirmation (§5).
3. Decompose `integrations/health_monitor.py` only after `llm_router`/`confidence_scoring`
   are migrated off it (§7).
4. Delete `fallback_chain_manager.py` together with the `intelligent_provider_switcher`
   / `performance_adaptive_router` dead cluster, once `llm_orchestrator` is retired.

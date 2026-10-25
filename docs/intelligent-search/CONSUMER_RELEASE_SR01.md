# Intelligent Search Consumer Release: SR-01

Status: **RED, implementation pending**. Branch: `work/intelligent-search-consumer-release`.

## Verified failure

The supplied live consumer session queried "Whats the weather" in General mode and received five Wikipedia sources and twelve ranked passages, including content about the band Weather Report. No actual weather observation or weather-specific clarification was displayed.

## Repo inspection

- `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/hooks/useIntelligentSearch.ts`: starts with `mode: 'general'`, sends selected mode, and clears results on option edits. Invalidates old results by sequence but does not demonstrate transport abortion.
- `src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py`: resolves explicit mode and passes it into InternetCapabilityService. Returns retrieved sources without an answer-synthesis guarantee.
- `src/ai_karen_engine/services/tooling/internet_capability_service.py`: `_resolve_mode()` uses explicit request mode first, then `SearchQueryPlanner.classify_mode()`. Dedicated `mode == 'weather'` observation handling exists. The service explicitly does not own final answer wording.
- `src/ai_karen_engine/services/search/search_query_planner.py`: uses keyword mode detection; lacks weather recognition; keyword `today` routes to news.
- `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/ResultsWorkspace.tsx`: excerpt/source tab-first UX, with fallback wording stating results are not a generated answer.
- `docs/INTELLIGENT_SEARCH_COMPLETION.md`: prior UI/API and mocked Playwright verification documented; live consumer-intent parity not demonstrated.

## Contract to implement

1. Consumer default is automatic intent routing. User-visible search modes are optional advanced overrides.
2. CORTEX owns eligible intent/capability decision. Runtime owns selection validation, policy, prompt construction, model usage, response synthesis, fallback and execution receipts. The plugin only performs governed capabilities, using canonical search/observation services.
3. Don't add another keyword classifier or model call to the search planner, plugin route or React UI. Reuse existing CORTEX, RuntimePolicy, ExpressionGateway and provider registry.
4. For weather, ask for missing location when needed, or resolve an authorized location from user context; do not fabricate conditions.
5. Synthesis may consume retrieved evidence and must cite it. If synthesis unavailable, label excerpts as evidence, not as an AI answer. Preserve degraded reasons for model, tools, persistence and presentation separately.
6. Keep prompt injection from retrieved material untrusted; enforce permissions and tenant isolation at final execution/persistence gates.
7. Present answer first, source cards second, diagnostics under advanced/admin controls. Preserve keyboard, screen-reader and responsive UX.
8. Audit the three search implementation trees for packaging vs active copies before consolidation or deletion.

## Proof matrix

| Scenario | Required result |
| --- | --- |
| What's the weather? | Weather intent, valid observation or location request |
| What's the weather in Detroit today? | Weather observation path, location and update time |
| Weather Report jazz band | General/music retrieval, never weather observation |
| Weather forecasting theory | Informational search rather than current observation |
| Latest weather research | Research/news retrieval with time/source handling |
| User forces advanced mode | Runtime-gated explicit override |
| Observation source unavailable | No fabricated readings; explicit degradation |
| Evidence exists, model unavailable | Labeled source excerpts, no fake answer |
| Search while changing settings | Previous completed result preserved |
| Cancel in flight | Transport abortion where supported; no stale UI overwrite |
| Chat follow-up | Bounded, cited evidence and consistent conversation correlation |
| Saved research across sessions | Durable permitted persistence/replay, tenant-safe |
| Permission denied | Backend rejection; no execution by hidden UI trick |

## Validation commands

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm run test
npm run build
npx playwright test tests/e2e/intelligent-search.spec.ts tests/e2e/intelligent-search-crawl4ai.spec.ts tests/e2e/intelligent-search-stale-response.spec.ts
```

These commands are **required**, not asserted to have passed.

## Release gates

P0: routing, truthful sourced answer, live provider verification, RBAC and provenance. P1: consumer answer-first layout, cancel/state preservation, research continuity, accessible source navigation. P2: comparison templates, source quality analytics and deeper research collections.

Consumer release stays **RED** until real provider + runtime + browser scenarios pass and human verification confirms the workflow. Never equate a green mocked component suite with real consumer readiness.

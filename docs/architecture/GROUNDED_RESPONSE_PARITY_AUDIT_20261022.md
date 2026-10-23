# GRA-01: Main-head generative response gap audit and repair contract

Status: **Source-verified defects; acceptance NOT yet complete**. Baseline: `main` after merged PR #502 (merge `43a3ca03ba3295aee317cd618e0bc7e3a6e9eb77`), checked October 22, 2026.

## What landed correctly
- The canonical `ChatRuntime` remains the execution authority and keeps API ingress thin.
- `DirectCapabilityExecutor` uses authorized plans, provides bounded tool metadata, and correctly leaves `actual_model=None` for direct-only tool answers.
- Verified weather/planner presentations are validated server-side in `presentation_contract.py`; the AG-UI projection emits `karen.presentation.v1` only for explicitly verified envelopes.
- assistant-ui can display structured weather presentations and `KarenHistoryRestoration.ts` attempts to restore validated structured content from owned message history.
- `ResponseContract`, `ResponsePromptBuilder`, `ResponseValidator`, and ExpressionGateway already exist: **reuse them**.

## Confirmed gaps on current main
1. **Direct-capability model bypass:** `chat_runtime.py:373` assigns `direct_result.text` as final answer. The only synthesis call at `:382` is for successful `search.general`, and `_synthesize_search_evidence` accepts only `fetched_page` sources. Current weather and time cannot qualify.
2. **Streaming parity failure:** `_run_direct_capability_stream` emits `result.text` directly at `:2396-2406`, bypassing the synthesis method altogether. This is the observed user-facing weather/time behavior.
3. **No verified grounding policy for numerical observations:** The existing search synthesis validator is citation-oriented, not an equivalence validator for units, observed conditions, dates or timezones. Simply passing arbitrary tool payloads to an LLM would risk invented highs, stale observation confusion, and prompt-injection.
4. **Independent degradation unproven:** A memory projection/recall failure is displayed with a weather result. Test that a successful tool observation is independently healthy even when recall fails, and distinguish response quality from infrastructure health.
5. **Surface vs durable contract:** `KarenHistoryRestoration` reads `structured_content` when provided, but this alone does not prove that production persistence writes the validated presentation atomically, or that read-after-restart replays it. Verify the entire backend write/read transaction before claiming this gate.
6. **Model attribution vs selection:** `actual_model=None` is correct for the direct executor. The UI must never imply that the selected Ollama model generated text unless the expression gateway returned a verified provider/model receipt. Test both response endpoints and history.

## Canonical implementation sequence
### GRA-01A: Shared grounded evidence contract
- In the existing runtime response ownership, normalize authorized factual evidence for `search.weather`, `time.current`, and fetched-page `search.general`. Bind evidence to the result source, correlation/request IDs, freshness, location and units. Never include arbitrary untrusted metadata or secrets.
- Preserve existing tool permission/RBAC and budget checks; fail closed on missing authorization or untrusted provenance. No new tool executor, registry, route, or memory store.
- Evidence can be successful independent of memory and model availability.

### GRA-01B: Single synthesizer through ExpressionGateway
- Extend the existing `_synthesize_search_evidence` responsibility into a centrally owned grounded-response composer, rather than adding a separate orchestrator.
- Reuse existing versioned response prompt builder, persona and allowed model selection, model budget, provider fallback policy, and response validator.
- For successful verified weather/time data: ask the authorized model for a brief natural response grounded strictly in normalized data, validate numerical facts, local time, timezone, and explicit missing fields before accepting. Reject fabricated forecast or altered readings.
- If composition is unavailable, provide an explicitly attributed, natural deterministic **evidence-only** response. Do not claim a model was used.
- Preserve `actual_provider`, `actual_model`, `runtime_engine`, `response_source`, `degraded_mode`, `degradation_reason`, `fallback_level`, and correlation metadata truthfully.

### GRA-01C: Stream/non-stream identical policy
- Invoke the same composition contract from `execute` and `_run_direct_capability_stream`; no separate weather-only streaming formatter.
- Stream progress/tool events separately from final assistant content, do not stream provisional raw tool text before composing. Only stream accepted model output or a clearly identified evidence-only fallback.
- Honor cancellation; do not append a different provider after partial model output.
- Persist the final answer once, with its validated typed presentation. Verify replay and assistant-ui renderer on reload.

### GRA-01D: Production acceptance and regression proof
- `search.weather` + healthy selected Ollama: test ExpressionGateway invoked once, input contains verified evidence, output is natural and facts match; actual model receipt must match execution.
- `time.current`: verify resolved IANA timezone, DST and actual timestamp are used, no model-derived clock values.
- Both modes: streaming and non-streaming contain the same factual values and provenance; verify AG-UI events do not masquerade as model output.
- Absent model, denied model, exhausted budget, timeout, injected tool instructions, stale readings, missing units, inconsistent high/low, malformed provider reply and invalid model hallucination: safe, honest result or unavailable status.
- Broken memory recall must not invalidate a successful weather observation; record separate health.
- Verify tenant isolation, RBAC, source authorization, cancellation, transaction rollback, replay after restart, XSS/URL allowlist, and 1-to-1 message persistence.
- Run `python -m compileall src`, targeted `pytest`, `ruff check src tests`, frontend `npm run lint && npm run typecheck && npm run test && npm run build`, then authenticated browser/live-model acceptance locally.
- No claim of passing full suites without execution receipts.

## Release rule
PR #502 is merged, but its generative response functionality must not be marked complete until both direct-answer modes invoke the selected model when authorized, and downstream metadata/history prove what actually ran. The next PR should remain bounded to existing runtime, response contract and targeted tests, not speculative new subsystems.

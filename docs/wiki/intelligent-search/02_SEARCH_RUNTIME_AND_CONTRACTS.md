# 02 | Search modes, execution path, types and API contracts

**Contract status:** observed `main` at 2026-11-20, except where marked **proposed** or **open PR**.

## 1. Consumer search API

Observed active frontend `services/IntelligentSearchApi.ts`:

```http
POST /api/plugins/execute
Content-Type: application/json

{
  "plugin_name": "intelligent-search",
  "parameters": {
    "query": "What is a temporal memory graph?",
    "context": {}
  }
}
```

An explicit advanced mode includes `parameters.mode`. Automatic mode intentionally omits the mode property in `useSearchPayload.ts`. Payload builder also places non-crawl options in `parameters.context`, and optional crawl controls in `parameters.crawl`. The canonical plugin dispatcher wraps typed `ExtensionExecutionContext` into `InternetExecutionContext` before calling `InternetCapabilityService.execute()`; never use the arbitrary request `context` object as identity or permission authority.

**Do not use `docs/INTELLIGENT_SEARCH_COMPLETION.md`'s historical dedicated `/api/plugins/intelligent-search/run` examples as current consumer ingress proof.** The UI's active wired path is `/api/plugins/execute`. If a dedicated legacy route still exists elsewhere, its ownership and use must be verified independently.

### Envelope and normalization

`IntelligentSearchApi.executeSearch` accepts direct search responses and supported plugin envelopes via `result`, `data`, or `payload`. It rejects false-success envelopes and response-shape violations; `status: needs_location` is an explicit clarification, not an ordinary success. A `status: error` or `failed` must never become a success card because it contains diagnostics.

Expected response fields (optional where mode does not produce them):

| Field | Meaning / rule |
| --- | --- |
| `query`, `mode`, `status` | Actual executed query, selected/observed mode, outcome; do not derive truth from draft UI mode |
| `summary` | Retrieval overview; **not assumed to be generated, verified synthesis** |
| `sources[]` | Search source records with URL, title, excerpt and fetched-versus-snippet evidence |
| `results[]` | Ranked passages/chunks with source URL and bounded content |
| `citations[]` | Backend citation records where returned; must map to source provenance |
| `extractedData` | Mode-specific structured output, including weather observation |
| `insights[]` | Backend-produced signals, not automatically researched claims |
| `diagnostics`, `crawl` | Technical counters, warnings, degradation |
| `metadata` | Provider, correlation/request IDs, timing, degraded status and selected strategy |
| `liveSearch` | Compatibility metadata; response intentionally does not embed unbounded crawler HTML/processed chunks |
| `evidenceGraph` | **Merged PR #1119**: bounded fetched-source and passage provenance graph, not a cognitive-memory relationship graph |

### Fetching full articles

The UI `IntelligentSearchApi.fetchArticle(articleId)` uses `GET /api/plugins/search/articles/{article_id}`. It validates returned article identity. This does **not** confer access to an arbitrary article ID: the backend must enforce authenticated article scope, source revision, permissions and availability.

In canonical `_build_sources`, `article_complete`, `article_preview`, `article_char_count` and `full_content` distinguish complete inline documents from partial previews. Current inline cap is 32,000 characters; larger articles are not labeled full, and stored-article fetching is a separate path.

## 2. Modes and configuration

`configs/modeConfig.ts` declares:

| Mode ID | Consumer intent | Advanced controls | Initial result lenses |
| --- | --- | --- | --- |
| `auto` | CORTEX/runtime-directed search | None | results, sources, extractedData, diagnostics |
| `general` | Broad web search | maxUrls, freshnessBias, domain filters, crawl | results, sources, extractedData, diagnostics |
| `news` | Recent reports | timeRange, preferRecent, domain filters | results, sources, extractedData, diagnostics |
| `docs` | Technical docs | product, version, officialOnly, docTypes | results, sources, extractedData, diagnostics |
| `deep_research` | Multi-source investigation | maxSubqueries, maxHops, sourceDiversity, crawl | results, sources, extractedData, insights, diagnostics |
| `structured_extract` | Structured information | schema, instruction, targetFields, targetSelectors | results, sources, extractedData, diagnostics |
| `weather` | Current observation and forecast | location, units, current/hourly/daily/alerts | results, extractedData, diagnostics |
| `stock_market` | Market context | ticker/company/exchange/news/earnings | results, sources, extractedData, diagnostics |

The seven executable handler classes are `GeneralHandler`, `NewsHandler`, `DocsHandler`, `DeepResearchHandler`, `StructuredExtractHandler`, `WeatherHandler` and `StockMarketHandler`. `auto` is UI/runtime routing behavior, not a distinct eighth handler.

**Source discrepancy to resolve:** The plugin manifest still declares default mode `general` while the consumer hook initializes mode `auto`. Verify which explicit/implicit decision actually reaches CORTEX, the plugin and InternetCapabilityService. Do not add another keyword or LLM router.

## 3. Search execution phases

`InternetCapabilityService.execute` normalizes request, establishes trusted context, applies authorization and mode/strategy resolution, discovers URLs, crawls permitted pages, processes passages, optionally extracts structured data, persists source articles where enabled, builds evidence/citations, and attaches observability metadata. It explicitly treats weather observations separately using the weather observation provider and supports `needs_location` rather than a fabricated forecast.

```text
query + approved options
  -> normalize InternetSearchRequest
  -> authorize + budget/provider selection per central runtime contracts
  -> resolve mode and query strategy
  -> source discovery -> crawl -> rank/chunk -> article reference persistence
  -> bounded source/result/citation/diagnostics response
  -> consumer renderer
```

### Config and budget boundaries in current code

- `InternetSearchRequest.from_payload` compresses query whitespace and rejects an empty query.
- `max_urls` is normalized between 1 and 25; concurrency between 1 and 10; timeout between 3 and 90 seconds in that request model. Other service policies and runtime budgets may further restrict effective values.
- When no URLs/pages can be retrieved, degradation and warnings must be accurate. A timeout is not success; authorization denial is not a fallback to public search.
- Search response includes `metadata.correlation_id` and `metadata.request_id` when the execution context provides them.
- Provider naming belongs to the central search registry/config. Legacy manifest keys are informational until proven active as canonical runtime settings.

### Crawl options mapping audit

`useSearchPayload.ts` strips the `crawl` prefix from camelCase controls (e.g. `crawlMaxPages` → `maxPages`) and adds `payload.crawl`. `InternetSearchRequest.from_payload` currently reads snake_case `crawl.max_pages` and `crawl.max_depth`. **This casing mismatch is a concrete contract to test/fix through one normalization boundary**, rather than assuming form controls affect actual crawl limits. Test the request payload at the kernel and InternetCapabilityService boundary, not only React.

Likewise, top-level `context` containing camelCase advanced controls must be compared to `handler.prepare` output and `InternetSearchRequest`'s accepted snake_case keys. Do not silently drop user limits or apply unchecked ones.

## 4. Truthful answer/synthesis contract

Fast retrieval is not identical to grounded final synthesis. Runtime, not a mode handler or React, decides whether a compatible authorized model produced an answer. At minimum, future structured answer output should distinguish `answer_source = model_generated | retrieved_evidence | unavailable`, citations by claim, source timestamps, actual provider/model, degradation reason and correlation IDs. **Those proposed fields are not a promise that the current API already emits them.**

Sources may be discovery snippets (`evidence_level: search_snippet`) or fully fetched (`fetched_page`). A snippet never proves the source article was read or its full claims were verified. No source evidence implies abstention or explicit no-results state.

## 5. Error cases to implement and test

| Case | Contract |
| --- | --- |
| `needs_location` | Prompt for location, no synthetic weather measurement |
| Missing live observation | Show provider unavailable, no fallback to unrelated retrieval |
| Explicit mode override | Honor only if authorized and supported; record actual mode |
| Unknown plugin/mode | Reject or degrade clearly; never auto-execute a different privileged capability |
| Search provider failure | Explicit degradation, source provenance intact |
| Source fetch fails | Distinguish discovered URL/snippet from fetched article |
| Untrusted article content | Do not execute embedded instructions, scripts or links as commands |
| Cancellation | Abort client transport and reject stale UI response; separately verify server worker termination if applicable |
| Article revoked/changed | Refetch or deny according to authorized revision fence |
| Saved research/readback | Requires real persisted, scoped receipt; not implied by React state |

## 6. Compatibility and versioning policy

Add optional fields to existing response shapes before requiring them; validate versions in the consuming UI. For substantial new graph/session APIs, define a typed, versioned backend schema and a non-graph fallback. Schema changes require API contract tests, E2E, backend migration/release notes and plugin package audits. Keep the old envelope behavior only while referenced by active consumers; delete compatibility shims once reference audit establishes safety.

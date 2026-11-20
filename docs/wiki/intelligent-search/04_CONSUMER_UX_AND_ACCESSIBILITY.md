# 04 | Consumer research workspace, UI states and accessibility

## 1. Current component tree

**Active frontend:** `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/`.

```text
IntelligentSearchPage.tsx
  SearchHeader
  SearchControlsPanel
    SearchQueryInput
    ModeSelector
    ModeSpecificControls
    CrawlOptionsPanel
  ResultsWorkspace
    ResultsPanel / SourcesPanel / ExtractedDataPanel
    InsightsPanel / DiagnosticsPanel
    ArticleReader / evidence inspector
    UIStates (loading, error, empty)
  useIntelligentSearch
    useSearchPayload
    IntelligentSearchApi
```

Observed on main at the wiki baseline: two-column search controls/results layout, optional advanced settings, tabs for sources/results/diagnostics and mode-specific views. It is a **source evidence explorer**, not a fully synchronized research graph. The plugin is mounted at the consumer route used by existing Playwright tests: `/plugins/intelligent-search`.

## 2. Target information architecture

Five synchronized **lenses** over a single authorized investigation snapshot:

| Lens | Main purpose | Required visible data | Blocked if |
| --- | --- | --- | --- |
| **Answer** | Understand the result | Actual runtime-generated answer with claim citations, or explicitly “retrieved evidence only” | No verified synthesis: cannot call evidence an AI answer |
| **Graph** | Explore relationships | Backend-authored nodes/edges with provenance and verification state | No source-backed relationships: show unavailable/empty, no illustrative fake graph |
| **Timeline** | Examine change over time | Actual valid/observed/recorded timestamps and supporting sources | Time evidence missing: show unknown or incomplete |
| **Evidence** | Inspect original sources | Search snippets versus full fetched article, citation spans, source revision, trust/freshness | Source inaccessible, revoked, stale or incomplete: label and gate |
| **Workflow** | Investigate/delegate actions | Runtime plan, dependency, approval, and execution receipts | Simple query: no invented agent workflow |

These are **planned** full-workspace capabilities. Merged PR #1119 adds a limited read-only source graph only when the backend returns `evidenceGraph`. Do not confuse that with complete graph-native investigation UX.

## 3. Layout rules

- **Desktop wide (1440px and up):** discover/search header, central answer and research area, optional right source inspector. Graph uses central canvas plus accessible adjacency list. Keep navigation compact; diagnostics collapsed.
- **Laptop/tablet (1024px):** reduce split columns; inspector is optional drawer; preserve citation access while reading.
- **Small tablet (768px):** search composer is primary, results full-width; graph list mode remains usable by touch and keyboard.
- **Mobile (390px):** a single-column question flow, bottom-sheet inspector if implemented, scrollable result lenses or accessible segmented selector, no tiny draggable nodes as the only graph navigation.
- Respect system reduced-motion, high-contrast, font zoom, sticky-focus visibility and safe-area insets. Avoid any design that requires dragging alone.

## 4. Source truth and UI states

| UI situation | Consumer behavior |
| --- | --- |
| Initial | Clear natural-language question, mode auto, no invented trending/history cards |
| Executing | Progress with honest activity, cancellable transport; don't imply server stopped |
| Completed with sources | Source-first if synthesis missing, verified answer if runtime confirms |
| Query edited | Keep last successful result as prior snapshot and show explicit “previous results” notice |
| Mode edited | Keep prior snapshot's panels/tabs tied to its **completed** mode, not new draft mode |
| Options edited | Preserve prior results but mark stale until explicit rerun |
| New execution failed | Preserve prior evidence where feasible and label it previous; show new run failure explicitly |
| Result empty | Clear no-evidence state, source-aware retry suggestions |
| Graph omitted | Existing Evidence/Sources views still work; no client-generated edges |
| Graph truncated | Announce limits and offer backend-governed pagination |
| Weather missing location | Ask for valid place, no synthetic weather report |
| Provider unavailable | Separate retrieval/provider failure from answer/synthesis failure |
| Source revoked | Remove denied link/content; do not show cached private quote |
| Action requested | Preview RBAC/permissions and consequences; show confirmed receipts |
| Clear | Explicitly remove draft and displayed snapshot; does not claim server-side deletion |

PR #1118 addresses preserving previous evidence through draft query/mode/settings changes, with a review correction to tie retained tabs to completed mode. **Merged 2026-11-20** after this wiki's original source audit. Avoid promising durability across reloads: the hook is in-memory UI state.

## 5. Search continuity and cancellation model

`useIntelligentSearch.ts` uses a monotonic request sequence and `AbortController`; an edit invalidates pending results so a late response cannot overwrite a more recent request. The current unmerged continuity slice adds `completedSearch` and `isResultsStale` metadata. These are display states only. A cancelled fetch does not prove server-side crawler cancellation or a detached worker's termination.

Future research sessions require a **server-generated** investigation ID, snapshot version and explicit persistence receipt. The UI may cache non-sensitive drafts for convenience but must not claim a saved investigation without durable confirmation.

Graph selection must not mutate the active search query automatically; user explicitly asks a follow-up from selected evidence, and the runtime revalidates selected server IDs.

## 6. Accessibility requirements

1. Semantic search form, named query field, labelled mode control and prominent submit state.
2. `aria-live`/status messages for results, stale notices, request errors and graph updates without excessive repeats.
3. All lenses navigable via keyboard, including focus return when inspector/drawer closes.
4. Graph always offers a list or adjacency/table representation; selecting a node by keyboard exposes the same links and evidence as pointer selection.
5. Accessible link labels distinguish source title, provider, fetched/snippet provenance and opening in a new tab.
6. Touch targets at least comfortably tappable; drag interactions optional. Reduced-motion applies to graph animation and loaders.
7. Contrast verified against real themes and dark mode. Avoid encoding support/contradiction or confidence only by color.
8. Source content is untrusted: render sanitized text, no HTML/script execution or uncontrolled `javascript:` URLs; external links use `rel="noopener noreferrer"`.
9. Use readable copy, short source snippets, progressive disclosure of provider IDs and diagnostics, and explicit freshness timestamps.
10. Run keyboard and screen-reader acceptance, not only static axe checks.

## 7. Core user journeys to prove

**Fast question:** query -> auto routing -> sources or runtime-cited answer -> open original source -> ask cited follow-up.

**Research investigation:** query -> multi-source evidence -> inspect Graph -> select a real relation -> inspect supporting passage -> expand via authorized runtime -> compare historical state -> save with durable receipt.

**Weather:** “What's the weather?” -> location clarification if absent; “weather in Detroit” -> actual provider observation with location/freshness. “Weather Report jazz band” must stay informational, not weather API.

**Source revoked mid-session:** open graph/source -> backend rejects now-invalid source -> UI replaces prior content with honest unavailable state, without revealing revocation details or stale protected content.

**Action handoff:** user chooses a confirmed proposal -> runtime checks identity, RBAC and plugin permissions -> action with audit/receipt -> UI displays actual state. Proposed plan is never marked executed.

## 8. Visual regression and artifacts

Playwright viewports: **390, 768, 1024, 1440px**. Capture desktop/mobile screenshots of initial, loading, answer/evidence, graph, selected node, errors, weather clarification and stale result, with source revision/CI run identified in filenames or test metadata. Store useful accepted screenshots in the repository's established test artifact/docs conventions; never commit sensitive source contents.

Focus on actual usability, not screenshot threshold tricks. If a screenshot fails, inspect layout before changing viewport, hiding unstable content or loosening thresholds.

## 9. Anti-patterns

- Huge permanently visible settings rail on mobile.
- Mixed old/new evidence without a stale label.
- Returning user to blank results when changing one advanced setting.
- A “graph” composed of invented connections based on frontend string matching.
- “Verified answer” label on retrieval overview or source excerpt.
- Fake confidence percentages, source ranking scores rendered as truth probability.
- Hiding errors under “successful” empty response envelopes.
- Treating plugin hook execution as permission to invoke another external integration.

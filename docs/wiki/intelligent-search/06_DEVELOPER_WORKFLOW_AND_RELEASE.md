# 06 | Development workflow, tests, operations and release gates

## 1. Prerequisites and source-first procedure

Use the active `agustealo/AI-Karen` repository, exact head and existing tools. Required stack varies by test: Python runtime/dependencies, Node.js frontend dependencies, PostgreSQL and Redis for integration, search/provider access and crawl engine availability for live acceptance. Do not imply that local mocked E2E exercises real external services.

Before work:
- Read [architecture](01_ARCHITECTURE_OWNERSHIP.md), [runtime contracts](02_SEARCH_RUNTIME_AND_CONTRACTS.md), [graph contract](03_GRAPH_MEMORY_AND_INVESTIGATION.md), [security](05_SECURITY_PROVENANCE_OBSERVABILITY.md) and [SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md).
- Inspect live `main`, open PR overlap, active UI manifest, plugin package copies and file references.
- Confirm whether the objective is source code, release verification, security fixes, graph projection or design. Do not combine unrelated slices.
- Record source owner, code touched, schema/contract version, expected degradation, rollback path and proof plan.

## 2. Local repository inspection

```bash
git fetch origin
git checkout main
git pull --ff-only
git rev-parse HEAD
git status --short

git grep -n "intelligent-search" -- src/ai_karen_engine src/ui_launchers free_plugins tests docs
git grep -n "InternetCapabilityService" -- src tests
git grep -n "LeanGraphService\|PostgresGraphRepository\|NeuroRecall" -- src tests
git grep -n "karen:inject-message\|evidenceGraph" -- src tests
```

These are **inspection commands**, not assertions that they were run for the wiki commit.

Canonical files to locate: backend `handler.py`; `services/tooling/internet_capability_service.py`; search registry and query planner; memory `graph/service.py`, `platform/memory/postgres/graph_repository.py`, `retrieval/neuro_recall.py`; consumer plugin page, hooks, mode config, API adapter and result components.

## 3. Targeted tests

Run from repository root unless a command changes directory:

```bash
python -m compileall src
pytest tests/extensions/test_intelligent_search_cortex_routing.py tests/extensions/test_intelligent_search_mode_contract.py tests/extensions/test_intelligent_search_status_truth.py -q
pytest tests/services/test_search_article_payload_fidelity.py tests/services/test_search_crawl_evidence_truth.py tests/services/test_search_discovery_snippet_survival.py tests/services/test_search_consumer_readiness_contract.py -q
pytest tests/core/memory/graph/ tests/core/memory/retrieval/ tests/core/memory/security/ -q
pytest tests/architecture/test_memory_temporal_graph_persistence.py tests/architecture/test_memory_temporal_graph_projection.py -q
ruff check src tests
mypy src

cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npx vitest run --config vitest.config.ts
npm run build
npx playwright test tests/e2e/intelligent-search.spec.ts tests/e2e/intelligent-search-crawl4ai.spec.ts tests/e2e/intelligent-search-stale-response.spec.ts
```

**Frontend unit tests:** The frontend `package.json` does not define `npm run test`. Run `npx vitest run --config vitest.config.ts` from `src/ui_launchers/Karen-AI-Theme`; its existing Vitest config selects unit/component test files and uses jsdom. **Browser/E2E tests:** Use Playwright separately with the checked-in project config; `npm run test:e2e` invokes `playwright test --config=e2e/playwright.config.ts` for that e2e project, while the explicit `npx playwright test tests/e2e/...` command above targets the plugin test files under the repository's root Playwright configuration. Check which suite/config is the required gate before running a subset. Neither suite alone verifies a live authenticated search backend.

If a test file/path is absent on the checked-out revision, adjust to the actual test tree and record why. Repository CI is authoritative for configured gates; commands above establish local checks but never replace exact-head job receipts.

**Current development slice tests:** Merged #1118 adds `tests/e2e/intelligent-search-research-continuity.spec.ts`; open #1119 adds `tests/e2e/intelligent-search-evidence-graph.spec.ts` and `tests/services/test_search_evidence_graph_projection.py`. The #1118 continuity test is on the current mainline. Run #1119 graph tests only on branches containing them or after its merge.

## 4. Contract test matrix

| Axis | Required tests | Proof requirement |
| --- | --- | --- |
| Intent | weather, jazz Weather Report, technical weather concept, news, documents, manual mode override | Actual CORTEX/runtime outcome versus request |
| Response | empty evidence, snippet-only, fetched article, partial article, synthesized answer, degraded model | No false answer or full-content claim |
| API | envelope success/failure/clarification, schema validation, article read revision | Consistent server truth |
| Crawl | enabled/disabled, page cap, depth, allowed/blocked domains, robots, timeout | Frontend payload actually governs backend effective limit |
| Continuity | query/mode/options edit, rerun, error, cancel, stale late result | Previous snapshot labeled and no stale overwrite |
| Graph | fetched-only edges, no fake inference, source URL mismatch, cyclic/dense neighborhoods | Bounded and authorized output |
| Security | missing tenant, wrong user, session swap, source revocation, prompt injection, forged graph ID | Fail closed with no leak |
| Accessibility | 390/768/1024/1440, keyboard, focus, screen reader, link labels, reduced motion | Real browser acceptance |
| Persistence | create, revision update, replay, revoke, concurrent write and deletion | Durable scoped receipt; no fake success |
| Telemetry | correlation propagation, provider, latency, degraded reason, redaction | Structured trace matches execution |
| Deployment | exact revision, production stack, signed origin/host, real auth and source provider | Release attestation, not preview-only success |

## 5. Authenticated browser acceptance

- Test the actual deployed consumer stack and authenticated user identity. Do not treat a Vercel frontend-only preview as proof the Python search backend is available.
- Follow [SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md) and its deployment verifier. Confirm immutable deployment revision, intended origin, cache policy, actual provider execution and persistence.
- Test a real query, real weather observation or accurate clarification, actual source article retrieval, source-to-chat followup, revoked access handling, and graph view when supplied.
- Verify viewports 390, 768, 1024, 1440px, focus restoration, keyboard access and screenshots. Record browser, URL/origin, commit SHA, test identity class, times and observed outcomes. Redact secrets/user content.
- Distinguish runtime status from UI success. An HTTP 200 wrapper can contain `success:false`, `status:error` or `needs_location`.
- A screenshot or mocked API `route.fulfill` test proves rendering, **not provider truth** or tenant isolation.

## 6. CI, reviews and merge discipline

1. Work in a focused branch with clear ownership and no duplicate implementation.
2. Update this wiki with code changes, new schema and test expectations.
3. Open PR with exact files, threat model, evidence/proof matrix and remaining risks.
4. Inspect code review and security findings, repair all material issues, add regression tests and respond on the correct review thread.
5. After a commit, **rerun checks on that exact head**. Old green CI is not proof of the new commit.
6. If `main` changes, reconcile intentionally, audit file overlaps, re-run fresh CI and review. No force-push/rebase that silently drops changes.
7. Merge only when required checks are green and review gates cleared; use expected SHA to prevent racing.
8. Verify post-merge mainline checks and, separately, authenticated deployment readiness. No “consumer ready” claim without target-host proof.

**Development update (2026-11-20):** PR #1117 architecture contract and PR #1118 search continuity are merged into `main` (#1118 squash commit `be559566bdb8bab0d67c868d4a156fa0f40ac21c`). PR #1119 evidence graph remains open and its reconciliation head `0eb0e1b7dcab076d259dc113afa723e2e6216075` requires fresh exact-head CI. Review GitHub live before relying on this snapshot.

## 7. Failures and incident triage

| Symptom | Inspect first | Do not do |
| --- | --- | --- |
| Weather query returns encyclopedia result | actual mode, CORTEX decision, weather location requirement | Add a new JS keyword classifier |
| UI displays provider error as successful sources | envelope normalizer and actual `status` | Hardcode success from HTTP status |
| Crawl limit ignored | `useSearchPayload` camelCase mapping vs backend snake_case parser | Claim UI slider enforces backend budget |
| Query edit loses research | `useIntelligentSearch` draft vs completed snapshot and tabs | Save temporary results as durable memories |
| Old response overwrites newer | AbortController, request sequence, test network race | Depend solely on disabling Search button |
| Graph draws unsupported relationship | actual backend source IDs, registry and verification state | Infer edge from frontend text |
| Memory source leaks | NeuroRecall source authorizer, scope and graph traversal | Filter after payload reaches browser |
| New PR unmergeable | current main SHA, changed-file comparison and review | Blind force-push or merge around failures |
| Source preview is incomplete | `article_complete`, article_id, full-content read/revision | Display preview as full fetched article |
| Authenticated deployment fails | backend deployment topology, revision verification, first boot | Assume Vercel frontend READY proves backend |

## 8. Rollback and compatibility

For a display-only graph change, feature-flag the lens or omit `evidenceGraph` and let existing Sources/Results continue. For schema changes, use approved migrations and reversible rollout paths; never delete canonical memory/graph tables without restoration proof. For response contracts, add optional fields first and retain tolerant readers, then remove compatibility only after import/reference and package audits. For provider failures, degrade honestly; no fake answer fallback.

## 9. Definition of done

**Code slice:** tests, lint/typecheck, source-owner review, security/tenant/provenance tests, exact-head CI, documentation updates, no stale references.

**Consumer readiness:** all code slices integrated + real authenticated provider/graph/workflow acceptance + release revision attestation + human UX/a11y review. These gates are independent. A merged PR is not a completed product experience.

## 10. Developer handoff

Use:

```text
Task ID and objective:
Current canonical owner:
Exact base SHA:
Files to modify / bundled copies to audit:
Schema/API changes and compatibility:
Threat model (RBAC, tenant, consent, provenance, prompt injection):
Telemetry/audit:
Tests and evidence required:
Expected degraded/empty states:
Merge and release gates:
Residual risks / blockers:
```

Do not omit uncertain behavior or mark a test passed unless a run receipt exists.

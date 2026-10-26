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


## Deployment verification update (October 26, 2026)

Repository quality checks were green at b0d4d9dddcfe05409673207fce6ccae2d0bfc63d.
Consumer release remains RED pending authenticated deployment acceptance.

The canonical scripts/ci/verify_deployment_revision.py fails closed for
non-HTTPS or redirected origins, missing or inconsistent revision metadata,
cacheable responses, oversized bodies and malformed JSON. The same verifier
runs before and after browser acceptance, with a final GitHub PR-head check.
All acceptance login scenarios reject unexpected origin redirects.

This is runtime self-reported revision evidence, not independent platform
build attestation. Vercel deployment ID, commit, READY status and immutable
URL must be verified separately. Manual workflow runs on another branch
without these guards are not PR #550 release receipts.


## SR-01 verified deployment topology and independent attestation (October 26, 2026)

**Consumer release: RED; repository checks: green at previous reviewed head.**

### Observed Vercel problem

Vercel project \`ai-karen\` currently selects framework \`python\` at repository root.
The preview built from the reviewed PR head
\`27cc86232b383b82688f068ebefb0247cbdc20a7\`
ended with \`PYTHON_ENTRYPOINT_NOT_FOUND\` and state \`ERROR\`.
This is a concrete project/runtime mismatch, not proof of a Python source defect.
Do not select an arbitrary \`server/app.py\` file or claim consumer readiness
from a superficially successful Python deployment.

### Canonical deployed consumer application

- \`deploy/compose/docker-compose.prod.yml\` owns the supported production
  \`web\` + \`api\` topology. The frontend is a Next.js application rooted at
  \`src/ui_launchers/Karen-AI-Theme\`.
- \`server.mjs\` is the canonical production web ingress and overwrites
  forwarded transport headers before backend proxying. Vercel's native Next.js
  runtime will not execute that custom ingress. A Vercel preview is therefore
  **not automatically equivalent** to the production Docker consumer stack.
- The frontend's API route handlers proxy to the Python backend. Running only
  the frontend with an inaccessible backend may build but cannot pass
  authenticated search, persistence, provider routing or health acceptance.
- Changes to the Vercel project framework/root must not be used as a proxy for
  full-stack release readiness. Preserve environment protection and production
  security requirements; do not publish a reduced-auth release for a green badge.

### Acceptance contract for a Vercel preview

The protected \`search\` workflow executes two **separate** sources of evidence
both before and after the browser tests:

1. \`scripts/ci/verify_vercel_deployment.py\`: independently fetches platform
   deployment metadata using the protected \`VERCEL_TOKEN\` and configured
   \`VERCEL_PROJECT_ID\` and \`VERCEL_ORG_ID\`. Requires a canonical HTTPS
   \`.vercel.app\` immutable deployment URL, project identity, \`git\` source,
   \`READY\` state, nonproduction target, source repository and full reviewed SHA.
2. \`scripts/ci/verify_deployment_revision.py\`: separately fetches the
   running application's non-cacheable, nonredirecting revision endpoint,
   requiring exact SHA parity. Neither observation replaces the other.

The workflow then runs real authenticated user search, source citations,
weather/location and durable replay. A post-test check requires unchanged
platform deployment, running revision and PR head.

**Required protected environment configuration:** \`KAREN_SEARCH_ACCEPTANCE_URL\`
must be the deployment's immutable HTTPS URL; \`VERCEL_PROJECT_ID\` and
\`VERCEL_ORG_ID\` must be protected environment variables; \`VERCEL_TOKEN\`
must be a least-privilege environment secret. Existing acceptance credentials
remain environment secrets, never committed or printed.

A separate provider-specific provenance adapter is required for self-hosted
Docker deployments. Never silently skip independent attestation, fabricate
provider readiness, or mark the consumer release green on frontend-only evidence.

### Proof remaining

- Verify a supported full-stack deployment with working canonical ingress,
  backend /api/health, model execution receipts, persistence and citations.
- Confirm exact deployment attestation and authenticated browser tests.
- Conduct human consumer UX acceptance on the same reviewed release image.

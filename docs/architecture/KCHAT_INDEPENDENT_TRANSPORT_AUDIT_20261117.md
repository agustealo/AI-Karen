# KCHAT-NET-02: independent OpenAI-compatible transport isolation

**Status:** draft source candidate; exact-head and live-host acceptance not yet established.  
**Date:** 2026-11-17  
**Dependency:** KCHAT-NET-01, merged PR #977 (canonical text/SSE proxy isolation).

## Reachable independent paths

- `ModelManager._build_runtime()` creates and caches `OpenAICompatibleRuntimeClient` for OpenAI-compatible provider endpoints. `ModelManager.generate_chat()` can invoke its `generate_text()` / `stream_generate()` through the existing compatibility interfaces; `embed()` and `health_check()` expose additional HTTP calls.
- The compatibility client's `_request()` and `health_check()` previously called `urllib.request.urlopen`, which could honor ambient `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and follow redirects. A nominally local target or a configured bearer credential could be forwarded away from the originally selected host.
- `OpenAICompatibleAdapter.discover_capabilities()` and `check_health()` used independent HTTPX clients with implicit environment trust. These read-only probes do not execute models and must not be confused with a model authorization or budget reservation.

## Narrow repair

1. The compatibility client reuses the Core-owned `provider_execution._open_provider_request()` for generation, embeddings, and health. This is the same short-lived, no-redirect, no-ambient-proxy urllib opener introduced and tested by PR #977. No second `ProxyHandler` implementation or global urllib opener is created.
2. Both discovery probes explicitly use `httpx.Client(trust_env=False, follow_redirects=False)`. Health and capability results continue to report backend responses; no invented fallback or model availability.
3. The existing Chat System Burn job is extended to run the compatibility-client and discovery-probe regression tests.

## Evidence and limits

- `test_openai_compatible_client_transport.py` poisons ambient proxy variables and checks that generation, embedding, and health pass through the canonical empty-`ProxyHandler` and redirect-denial opener, with the expected bearer header and timeout. A real loopback HTTP server issues a redirect for a model completion and verifies that no request reaches its redirect target.
- `test_openai_compatible_adapter.py` asserts that the capability and health probes never enable ambient proxy handling or redirects.
- This candidate does **not** establish full authorization and budget admission. `ModelManager.generate_chat()` and direct `OpenAICompatibleRuntimeClient` invocations do not require a `ChatExecutionContext`, an exact `AuthorizedExecutionPlan`, or a shared `ExecutionBudgetMeter` before actual inference. The compatibility client remains a separate request construction and response-parsing implementation; reuse of the hardened socket opener is not unification of model execution authority.
- No DNS-to-IP pinning, public-IP rejection after DNS resolution, network namespace egress proof, intentionally configured proxy support, external vendor traffic capture, or consumer host acceptance is claimed. The same applies to other SDK and integration HTTP clients until individually audited.

## Next security gate: KCHAT-AUTH-05

Trace **all** production and test callers of `ModelManager.generate_chat()`, `invoke_provider()`, `resolve_runtime()`, and `OpenAICompatibleRuntimeClient`. Before allowing nonlocal model or embedding inference through those interfaces, require the canonical RuntimePolicy-bound authenticated plan, eligible provider/model check, and actual attempt charge against the same execution budget. Preserve local-first execution and explicit fail-closed unavailable behavior; do not add a parallel authority, permit a client-built grant, or silently treat standalone compatibility calls as authorized. Audit the remaining independent SDK clients and DNS/socket egress in separate measured gates.

Do not mark KCHAT-AUTH-05 or target-host egress certification complete from this transport-only patch.

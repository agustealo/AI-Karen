# KCHAT-NET-01: canonical provider transport network-path admission

**Status:** source candidate, no exact-head or live-host acceptance claimed.  
**Date:** 2026-11-16  
**Dependency:** KCHAT-AUTH-04 (#965) and KCHAT-BUDGET-03 (#970) already merged.

## Authority and observed risk

`provider_execution.py` is the one Core-owned OpenAI-compatible HTTP transport for regular chat, SSE streams, and structured tool calls. `ChatRuntime` and RuntimePolicy own authorization; `ExpressionGateway` and the governed LangChain model perform the existing scoped attempt checks and budget reservations. Transport does not select models, build prompts, store responses, or grant RBAC.

The registered endpoint's effective URL is classified before the existing canonical chat and Deep Agents calls. That check is not sufficient if the process supplies an ambient `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY`: urllib's `build_opener` implicitly adds a default `ProxyHandler`, and HTTPX's `AsyncClient` defaults to `trust_env=True`. A nominally local request could be relayed to an external host, including prompt data and, when configured, a bearer credential. `NO_PROXY` cannot be considered a security boundary.

## Change in this slice

- The synchronous text and structured-tool transport builds a per-call opener with the existing redirect-denial handler **and** an explicit empty `ProxyHandler({})`. This suppresses implicit process proxy discovery and preserves the non-global, no-redirect API.
- SSE uses `AsyncClient(trust_env=False, follow_redirects=False)`, retaining the existing streaming deadline, cancellation and verified terminal receipt semantics.
- No new provider registry, backend router, env bypass, emergency model response, or transport-specific RBAC policy is introduced.
- Existing personal-model Vault key acquisition and audit remain authoritative. Explicit, centrally authorized egress proxies would require an independent reviewed registry/policy design rather than accepting ambient variables.

## Proof

- `tests/core/model_runtime/test_personal_model_transport_grant.py` validates the empty urllib `ProxyHandler`, no redirects, and adversarial process proxy settings for a local target. The streamed personal-credential transport also asserts `trust_env=False`.
- `tests/core/model_runtime/test_provider_execution_stream.py` verifies that proxy-poisoned environment settings cannot redirect an observed local SSE request and keeps existing receipt/cancellation tests.
- Main Quality already executes both files; the Chat System Burn transport step is extended to include the personal transport security tests.

## Not certified by this change

This is **not** a complete raw-transport admission contract. Independent code that calls `execute_provider_endpoint`, `stream_provider_endpoint`, or `execute_structured_provider_endpoint` still needs call-site reachability and authenticated plan/meter proof. Effective-URL check/use drift, DNS rebinding, hostname resolution, external NAT or network overlays, intentionally configured explicit proxies, direct sockets, and separately implemented SDK clients remain separate evidence gates. Do not treat source-level proxy isolation as real target-host traffic capture or consumer-ready network egress attestation.

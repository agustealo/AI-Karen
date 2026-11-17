# KCHAT-AUTH-05A: deny ungoverned external compatibility inference

**Status:** stacked source candidate; release CI, merge, and target-host egress remain unverified.  
**Date:** 2026-11-17  
**Depends on:** merged #970 (Deep Agents budget), #977 (canonical no-proxy egress) and #979 (independent compatibility no-proxy/redirect).

## Confirmed raw execution paths

- `ModelManager.resolve_runtime()` caches an `OpenAICompatibleRuntimeClient` for OpenAI-compatible provider endpoints. `ModelManager.generate_chat()` can use it without carrying the original authenticated execution scope or shared budget. The `ModelManagerInferencePort` is a concrete caller.
- `LLMUtils.get_provider()` exposes the same cached runtime. `LLMUtils.generate_text()`, `generate_text_async()` and `embed()` can invoke it without the original admission.
- Public `OpenAICompatibleRuntimeClient.generate_text()`, `generate_response()`, `stream_generate()`, `embed()` and `_request()` can be called independently of either wrapper. A router-only guard would be bypassable.
- `small_language_model_service.py` uses a separate `FallbackProvider` path; do not mistake it for the cloud-compatible client or keep its canned output as a production model answer.

## Narrow fail-closed repair

The canonical shared destination classifier also excludes IPv4 `169.254.0.0/16` and IPv6 `fe80::/10` from the trusted local-model set. The old classifier silently allowed cloud instance-metadata and interface-local targets as local traffic. IPv4-mapped IPv6 addresses are normalized before this decision. Existing loopback, Docker bridge aliases and RFC1918/ULA model-serving addresses retain their configured local-first behavior. The metadata/link-local policy is enforced for both compatibility and governed ExpressionGateway admission; in addition, the canonical HTTP opener unconditionally rejects link-local, unspecified and multicast IP literals **even if external provider execution is authorized**. Noncanonical numeric IPv4 aliases (single-integer decimal, hexadecimal and octal/dotted-octal forms) are rejected before the opener using the standard-library numeric-only IPv4 parser; this check performs no DNS query. Percent-escaped URL authorities are also rejected because urllib decodes them for the actual Request host, and a request whose host differs from its URL authority is refused before opener construction. Escapes inside a URL path remain supported. No ambient-proxy or redirect logic is weakened. Tests assert forbidden destinations never reach the opener, while ordinary loopback still does.

The compatibility client cannot validate a `ChatExecutionContext`, an exact `AuthorizedExecutionPlan`, or a shared `ExecutionBudgetMeter`. Therefore it may not emit **nonlocal** inference or embedding HTTP at all. Before constructing a `Request`, and again for health probes, the raw compatibility transport asks the **existing canonical** `provider_endpoint_requires_external_permission()` classifier to evaluate its current actual URL. Cloud/unknown/invalid destinations fail closed with `ungoverned_external_compatibility_transport_denied`. A local-looking provider ID cannot override the check; mutating `base_url` is evaluated per attempt. No duplicate provider registry, RuntimePolicy service, network-locality classifier, budget, fallback or global urllib state is introduced.

The already-governed ChatRuntime/ExpressionGateway and Deep Agents transports continue to own explicitly authorized external model execution. This shim **does not** issue new external permissions or claim support for authorized external calls through this legacy interface.

## Proof

`tests/core/model_runtime/test_openai_compatible_client_admission.py` covers direct generation, response, pseudo-stream, embedding, raw request and health paths for public/unknown/malformed destinations; it asserts **zero wire calls** and verifies that a local-labeled provider, credential, or post-construction URL change cannot bypass the guard. A separate inference-port integration test proves that the concrete `ModelManagerInferencePort -> ModelManager.generate_chat -> OpenAICompatibleRuntimeClient` chain cannot create an ungoverned remote request. Chat System Burn runs the regression alongside #979 transport tests.

## Not certified

- This is **not** KCHAT-AUTH-05 complete. Local compatibility inference still lacks request-bound RuntimePolicy and actual `ExecutionBudgetMeter` reservation; the `LLMUtils` and raw-port APIs must be migrated to the canonical governed runtime before full admission certification.
- Raw transport still constructs a second OpenAI-compatible HTTP request/response path. Consolidation and correct model attribution/receipts remain necessary.
- Registry model/endpoint eligibility, dynamic DNS resolution and rebinding, DNS-to-IP pinning, socket/NAT capture, external-proxy policy, direct SDK clients, and external discovery probes remain separate risk gates. The link-local address exclusion is source-tested but not yet proved by target-host packet capture.
- No consumer-ready local model run, post-merge CI, production-packet capture or billed-cloud-provider proof is claimed.

## Next work

KCHAT-AUTH-05B: inventory each active inference-port and LLMUtils caller, propagate a trusted Runtime-issued `ChatExecutionContext` + immutable plan + original shared budget to a single canonical transport, enforce provider/model/capability eligibility and charge every actual request including local, embedding, nested and retries. Deny any missing or mismatched scope before wire; preserve existing tenant audit, telemetry, provider provenance and local-first selection. Remove the legacy raw client after references and tests prove migration. Then test live network egress and DNS-to-IP behavior separately.

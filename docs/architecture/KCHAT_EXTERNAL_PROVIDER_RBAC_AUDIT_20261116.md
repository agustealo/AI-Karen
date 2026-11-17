# KCHAT-AUTH-04: authenticated external model execution admission

**Date:** 2026-11-16  
**Source candidate:** `fix/chat-external-provider-rbac-20261116`  
**Dependency:** PR #958 merged at `d882f82eb007c1d5cc23985f8dfe080554a2cf89`  
**Release state:** source candidate; exact-head CI required before merge.

## Defect and authority

PR #958 enforces the installation-level `allow_external_engines` opt-out at actual ExpressionGateway execution, but an enabled external provider can still execute without verifying `require_admin_for_external` against the authenticated caller. `ExpressionTask` previously carried no privileged external execution grant; a UI or model provider preference is not authorization.

This patch preserves a single responsibility per authority:

- **Authenticated ingress:** `ChatExecutionContext.require_authenticated_user()` is the original, scope-checked trusted principal, not metadata roles or the model's assertion.
- **RuntimePolicy:** `authorize_external_provider_execution` verifies installation opt-in, the original user/tenant/session-bound execution plan, and canonical `ADMIN_PROVIDERS_MANAGE` RBAC permission when admin approval is required. An explicit administrator-disabled `require_admin_for_external=False` still allows authenticated ordinary users, but never overrides `allow_external_engines=False`.
- **ChatRuntime:** binds a non-serializable trusted async callback to all existing `ExpressionTask` construction paths: direct/streamed chat, grounded synthesis, and surface-layout planning. No duplicate policy object, separate permission cache, or route-level check.
- **ExpressionGateway:** invokes the callback before every configured cloud engine attempt, after disabled/circuit-open filtering but before another model-call reservation, engine instantiation, or network execution. Missing, malformed, denied, or raising guards are fail-closed and logged with bounded codes without private exception content.
- **Existing ExecutionBudgetMeter:** continues to meter only actual permitted fallback engine attempts. A refused cloud fallback cannot use an extra model attempt.

## Proof

- `tests/core/runtime/test_external_provider_rbac.py`: administrator and ordinary user, request-role spoof, inactive/unverified principal, missing principal, foreign user/tenant/session, missing decision ID, installation opt-out and explicit non-admin execution policy.
- `tests/core/expression/test_gateway_additional_engine_budget.py`: reject unguarded cloud, admit exact True, reject malformed and throwing approvals, preserve local fallback and proper quotas.
- `tests/core/runtime/test_chat_generation_budget.py` and `test_ksi_surface_planning.py`: ensure the trusted callback travels with all ChatRuntime expression tasks.
- `.github/workflows/chat-system-burn.yml`: explicit exact-head role-gate test invocation.

## Residual, separately gated work

This patch covers cloud engines executed through ExpressionGateway; it does **not** certify all SDK-internal provider retries, every agent's nested model call, or independent provider transport paths. A separate reachability audit is required for legacy `ProviderRuntime._attempt_provider_with_retries`, which contains a retry loop but is not proven active in canonical ChatRuntime. Remote destination admission now happens inside the canonical `OpenAICompatibleEngine` **before** either streaming or non-streaming network execution. The provider transport's `provider_endpoint_requires_external_permission` resolves the effective configured/env-overridden URL and treats cloud, nonlocal, unknown-DNS, malformed and public-IP destinations as external even when `EndpointKind` defaults to local. It conservatively recognizes loopback, RFC1918/ULA/link-local addresses and explicitly named Docker host bridge aliases. Nonlocal destinations invoke the *same* RuntimePolicy-bound callback, failing closed without a model request if absent, malformed, or denied. The additional adversarial suite is `tests/core/expression/test_external_endpoint_admission.py`, included in Chat System Burn.

This remains a canonical **chat-engine** contract, not proof that independent direct provider transport or SDK agent calls are governed. DNS rebinding, proxying, local bridge alias remapping, and the trust status of remote LAN infrastructure are separate deployment security questions; a URL classifier alone cannot prove actual socket destination or invoice usage. Provider billing and customer latency cannot be established from unit test doubles.

No runtime authority, plugin permission, provider registry, or UI fallback is duplicated. Never merge before latest exact-head Chat Burn, RBAC, Main Quality, Medusa, Plugin Ecosystem, real PostgreSQL, Ollama E2E and first-boot acceptance.

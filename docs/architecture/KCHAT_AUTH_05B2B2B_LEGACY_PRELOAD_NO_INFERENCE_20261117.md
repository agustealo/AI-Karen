# KCHAT-AUTH-05B2B2B: no ungoverned model generation during legacy preload

**Status:** scoped source candidate. Depends on merged #990, #991 and the 87-candidate, source-only caller census from #996. This does **not** certify all model execution paths.

## Source-of-truth and runtime boundary

The legacy `LLMOrchestrator` bootstrap can register provider objects before a user has sent a request. This is metadata discovery, not a RuntimePolicy execution decision. Before this change, `_preload_providers` and `_ensure_fallback_provider` called `_warm_model`. That helper either invoked `provider.warm_cache()` or directly invoked `ModelManager.invoke_provider_sync(provider, "hello", max_tokens=1)`. Neither path received an authenticated `ChatExecutionContext`, an `AuthorizedExecutionPlan` or the original `ExecutionBudgetMeter`.

Even the opt-in `KARI_ENABLE_PROVIDER_PRELOAD` or legacy `KARI_WARM_CLOUD_PROVIDERS` flags cannot grant these permissions. Startup model latency is not evidence of real authorized request execution.

## Repair

- Preserve optional discovery and registration of the selected provider-model metadata, existing tags, weights, fallback catalog and honest health reporting.
- Remove the implicit `warm_cache`/generation fallback at model registration and fallback registration. Delete the now-dead `_warm_model` and `_should_warm_provider` helpers rather than retaining an unauthorized compatibility implementation.
- Leave newly registered model records **unwarmed**; no synthetic latency, model receipt or warmed status is produced. The existing `_track_latency` may mark a model warm only following the actual routing/execution evidence it receives.
- Reuse RuntimePolicy, the existing Core `GovernedToolModelAdmission`, and the original shared budget for any genuine model invocation. This PR introduces no provider/model router, grant, meter, API or policy.
- Preserve the default-disabled registry preload option, but it now means registry setup only. There is no replacement warmup flag or background inference bypass.

## Proof and limits

`tests/core/model_runtime/test_legacy_preload_no_inference.py` uses providers that raise on `warm_cache`, generation and embedding, checking both local and remote registry entries, fallback registration and idempotent fallback refresh. It also verifies that actual observed latency can still set `warmed` without pretending startup generated text.

The tests run in Chat System Burn and compile the touched legacy runtime. Required gates remain Main Quality, Chat System Burn, Medusa, Ollama Live E2E, First-Boot and independent review. Direct caller census results are **static leads**, not established reachability.

**Residual risk:** provider construction via `registry.get_provider` may itself allocate or load model resources, and health checks may use their own separate transport. This patch eliminates explicit warm-up generation from these call sites, not all possible constructor side effects. Direct `ModelManager.generate_chat` without admission, raw `invoke_provider` / `invoke_embedding`, legacy embedding APIs and full external socket/egress enforcement require separate migration. Do not infer that this patch grants startup execution, real model availability, or complete KCHAT-AUTH-05B2 security acceptance.

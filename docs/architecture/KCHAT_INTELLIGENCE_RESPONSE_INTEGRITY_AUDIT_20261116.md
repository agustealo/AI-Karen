# KCHAT-INT-01: Real-generation integrity audit

**Date:** 2026-11-16  
**Repository:** `agustealo/AI-Karen`  
**Status:** Code-level mitigation proposed. Live authenticated model acceptance remains unverified until observed on the target host.

## What "real intelligent response" means

A pleasant-looking sentence is not evidence of generation, reasoning, retrieval,
memory, or tool execution. Treat these as separate, verifiable capabilities.

A successful ordinary chat turn must have:

1. An authenticated and tenant-scoped request, canonical CORTEX decision and
   authorized runtime execution plan.
2. PromptRuntime-produced messages containing the permitted instructions,
   selected persona, authorized conversational context and governed recall.
3. An actual successful request to a registered, authorized model endpoint,
   preserving a matching task receipt and the observed provider **and model**.
4. Nonempty text passing response validation from an explicitly generative
   response source. A disabled adapter, emergency static text, old transcript,
   or deterministic failure message must never qualify as model-generated.
5. Honest fallback/degraded attribution and no mixed-provider partial stream.
6. An independently persisted user/assistant turn, with accurate memory and
   transcript metadata, before declaring completion.

This contract proves **execution provenance**, not that every answer is
semantically correct. Intelligence quality requires separate real-model
evaluation, with blind scoring and auditable evidence.

## Source-of-truth review

| Responsibility | Canonical owner | This audit's disposition |
| --- | --- | --- |
| Authenticated API transport | `api_routes/chat/runtime.py` | Keep thin; no routing changes |
| Intent, requirement and authorization decisions | `core/cortex/executive.py` + RuntimePolicy | Keep decisions separate from execution |
| Response execution, memory and transcript | `core/runtime/chat_runtime.py` | Keep single execution authority |
| Prompt assembly | `core/runtime/prompt/` | Reuse existing versioned prompts |
| Generative engine selection and model-receipt acceptance | `core/expression/gateway.py` | **Fix provenance admission at this existing boundary** |
| Provider endpoint execution | `core/expression/engines/openai_compatible_engine.py` and `core/model_runtime/provider_execution.py` | Retain native terminal completion and selected model checks |
| Consumer/UI | Chat client components | Render backend truth; never invent model status |

Legacy `core/runtime/provider_runtime.py`, `server/chat/`, LangGraph
formatters and agent composers require call-site classification before any
deletion or migration. They are **not** grounds for creating another chat
orchestrator.

## Confirmed code-level defects

### INT-01A: Non-generative text may pass the model admission check

Before this change, the gateway classified a result as model sourced if it
contained any truthy `provider` and its `response_source` was not exactly
`model_unavailable`. It did **not** require a model ID, a matching task ID,
or a positively recognized generative source.

Thus a malformed or stale in-process engine receipt with usable text and
`response_source="emergency_static"`, `engine_disabled`, or
`persisted_history` could satisfy the gateway's acceptance predicate.
This is a **code-path finding**, not proof that such a receipt was observed
in a production user session.

**Repair:** At the existing ExpressionGateway admission boundary, require a
matching task, nonblank provider and model IDs, and a recognized generative
source. Reject all other receipts and attempt only eligible, configured
fallbacks before any streamed text. If none succeed, raise
`EngineUnavailableError`; do not synthesize a model-shaped reply.

### INT-01B: Fallback success can report healthy primary status

Before this change, successful engine results at fallback index greater than
zero were returned with fallback metadata but the engine-provided
`degraded=False` could remain unchanged.

**Repair:** The gateway marks a secondary model result as degraded and
assigns `model_engine_fallback` if no specific degradation reason exists.
Actual provider and model remain the provider's observed receipt, not the
requested target.

### INT-01C: Legacy test expectations equated static result with completion

Prior tests expected disabled/emergency engine text to complete a model call.
These expectations contradicted the current gateway docstring and the
canonical ChatRuntime fail-closed behavior. They are updated to require an
explicit `EngineUnavailableError`.

## Regression matrix

| Case | Required behavior |
| --- | --- |
| Valid primary model identity and text | Accept; no synthetic degradation |
| Missing/blank provider or model | Reject; no successful model receipt |
| Foreign request/task receipt | Reject |
| Static/emergency/persisted-history source with model-like text | Reject |
| Primary produces invalid source then secondary generates | Accept secondary; mark degraded with true fallback metadata |
| No valid model available | Raise unavailable; never return canned answer as generated |
| Primary streamed text then fails validation | No second model; incomplete stream error |
| Genuine partial output ending due to output token limit | Preserve actual model, mark truncated/degraded; no invented completion |

**Offline proof:**

```bash
python -m compileall src/ai_karen_engine/core/expression
ruff check src/ai_karen_engine/core/expression/gateway.py tests/core/expression
pytest -q tests/core/expression/test_gateway_generation_integrity.py
pytest -q tests/core/expression/test_gateway_selected_provider_precedence.py tests/core/expression/test_expression_stream_fallback_integrity.py tests/core/expression/test_gateway_fallbacks.py tests/core/expression/test_gateway.py
pytest -q tests/core/runtime/test_chat_runtime_stream_contract.py
```

**CI proof:** Exact-head Main Quality, Chat System Burn, backend quality and
provider execution checks. Do not merge with failing required checks.

## Next: live intelligence and conversational quality acceptance

Use real authenticated runtime execution with an actual configured local
model, not mocks. Record scoped request/correlation IDs and redacted
provider receipts for these independent evaluations:

1. **Intent and follow-up handling:** multi-turn anaphora, corrections,
   ambiguous commands, context switches, and a new tenant/session.
2. **Prompt/context:** prove correct prompt version, persona and consented
   memory recall; no stale user identity or cross-tenant influence.
3. **Reasoning calibration:** multi-step factual questions with known ground
   truth, counterexamples, uncertainty and abstention where evidence is absent.
4. **Grounded tools:** observed clock/weather/search/plugin read answers with
   fresh evidence and no unsupported numerical invention.
5. **Provider resilience:** genuine disconnected endpoint, empty completion,
   invalid model receipt, 429/timeout, partial SSE and cancellation.
6. **Response persistence:** verify exact accepted text, provider and
   fallback attribution survive HTTP/SSE and durable transcript readback.
7. **Quality scorecard:** task completion, factual correctness, grounded
   citation accuracy, instruction adherence, continuity, recovery honesty,
   latency and human preference. Capture raw judge scores separately from
   rewards or training labels, with consent and provenance.

Measure the baseline and revised runtime against the **same prompts and
model revisions**. Never declare generalized intelligence or hallucination
elimination from unit tests alone. Production-ready acceptance requires an
observed model session and passed evaluation thresholds approved by the
release owner.

# KCHAT-AUTH-05B2B1: read-only direct execution caller census

**Status:** candidate, not an authorization repair. Depends on merged #990 and #991.

## Ownership

ChatRuntime and RuntimePolicy remain the only authenticated execution-plan issuers.
Core `governed_model_admission.py` remains the validator and original shared
budget reservation authority. This candidate adds a **static audit utility only**
and changes no model, embedding, network or plugin runtime execution behavior.

## Motivation

The 05B2A migration protected `LLMUtils` and `ModelManagerInferencePort`, but
direct `ModelManager.generate_chat` / `generate_embedding`, provider invocation
helpers, raw local compatibility clients and old `EmbeddingManager` fallback
APIs remain candidates for ungoverned access. Reaching directly for a global
deny would risk breaking authorized production paths and double-charging
ExpressionGateway/Deep Agents callbacks before their active callers are known.

## Output

Run:

```bash
python scripts/ci/kchat_auth_05b2b_caller_census.py \
  --root src/ai_karen_engine \
  --output build/kchat-auth-05b2b-caller-census.json
```

The deterministic JSON report carries scanned-file counts, parse errors,
candidate method/class callsites with source file, line, scope and a bounded
receiver identifier, and boolean hints for an explicit `execution_admission`
or selected-model keyword. It records no prompt arguments, secrets, message
contents or model results. Scan errors make the command fail, never a false
clean report. Chat System Burn uploads the JSON as an artifact for review.

**Not proof:** static syntax cannot establish reachability, missing indirect
aliases, C-extension/SDK calls, runtime dispatch, actual transport destination
or whether an upstream gateway already reserved the original meter. A caller
with an admission keyword is not automatically authorized. All candidates
remain `unverified_candidate` until manually classified.

## Next audited code migration

1. Review static findings against runtime call graph, tests, SDK entrypoints,
   workers and installed plugins; classify active/correct, misplaced, legacy,
   dead and dynamic-unknown. Inspect original plan/meter identity for each.
2. Migrate active execution to authenticated Core admission before deleting
   compatibility entrypoints or enforcing universal fail-closed behavior.
3. Preserve the ExpressionGateway pre-reserved first call, retry budget,
   external RBAC and model receipt integrity. Avoid a new authorization owner.
4. Prove negative cases with no provider/socket calls or consumed quota;
   prove real local/remote/embedding paths and nested attempts consume exactly
   the same original budget. Keep DNS/socket proof separate.
5. Re-run Chat System Burn, Main Quality, Medusa, First-Boot and Ollama
   exact-head gates. Do not mark KCHAT-AUTH-05B complete until all proof lands.

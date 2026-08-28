# Intent Classifier Authority

Status: active audit contract

## Ownership

Intent classification is a CORTEX decision concern. IntelligenceRuntime and its ML predictors may produce evidence and scored intent signals, but they do not authorize actions, choose providers, execute plugins, bypass RBAC, or own runtime routing.

The intended authority chain is:

1. Runtime normalizes the request and assembles authenticated tenant/session context.
2. IntelligenceRuntime produces linguistic, semantic, intent, ambiguity, domain, capability, and topology signals.
3. CORTEX consumes those signals plus policy/RBAC context and decides the canonical intent/routing decision.
4. Runtime executes the authorized decision.
5. API and UI expose backend truth only.

## Current live surfaces

The repository currently contains three intent-like surfaces:

- `core/intelligence/ml/predictors/intent.py`: semantic/heuristic intent signal producer.
- `core/cortex/intent.py`: legacy basic substring resolver.
- `core/cortex/routing_intents.py`: capability/live-data routing matcher.

These are not equivalent authorities. The ML predictor is evidence. Capability routing is a CORTEX routing contract. The legacy basic resolver is compatibility debt until a zero-reference audit proves it can be deleted or its consumers are migrated.

No new classifier should be added beside these surfaces. Convergence must collapse consumers toward one CORTEX decision entrypoint rather than creating a fourth classifier.

## Classification contract

A classifier signal must report truthfully:

- prediction task
- label, including explicit `unknown`
- confidence in `[0, 1]`
- probability when available
- model and feature provenance when available
- whether fallback/degraded logic was used
- inference method
- latency
- non-sensitive diagnostic metadata

An encoder fallback must not be reported as transformer/model truth. A weak semantic match must not be forced into a supported class. Unknown or unsupported inputs must remain unknown.

Confidence is evidence strength, not authorization. A high-confidence intent never bypasses RBAC, tenant isolation, policy gates, approval requirements, or tool/plugin permission checks.

## Burn invariants

The permanent classifier burn suite must prove at least the following:

| Class | Burn case | Required behavior |
| --- | --- | --- |
| Specificity | `Can you fix this broken authentication error?` | problem-solving signal wins over generic request phrasing |
| Decision | `Which database should I choose?` | decision-making signal |
| Creative | `Brainstorm three names` | creative-assistance signal |
| Information | `Explain vector recall` | information-seeking signal |
| Task | `Please build the checklist` | task-completion signal |
| Social | `Hello there` | social-interaction signal |
| Noise | random IDs/punctuation/emoji | `unknown`, never fabricated social intent |
| Boundaries | `whatsoever` | must not trigger the token `what` |
| Weak semantic | orthogonal request/template embeddings | reject semantic classification and fall back honestly |
| Degraded encoder | hash/fallback semantic encoding | must not claim transformer provenance |
| Efficiency | semantic request | encode request once per prediction |
| Public API | `classify("intent", ...)` | return registered predictor truth, not decorative `unknown` metadata |
| Unknown task | unsupported prediction task | explicit fallback/unknown result |

Future burns should add multilingual/paraphrase evaluation, multi-intent ranking, adversarial quoted instructions, calibration datasets, and tenant/context-sensitive routing once the canonical CORTEX decision envelope exposes those fields.

## Known authority debt

### P0: split classifier ownership

`core/cortex/intent.py` and `core/cortex/routing_intents.py` both perform independent substring classification while the ML predictor produces a third intent vocabulary. This violates the one-responsibility/one-owner rule.

Required convergence:

- inventory every consumer of both CORTEX modules
- define one canonical CORTEX intent/routing decision envelope
- feed IntelligenceRuntime intent signals into that entrypoint
- preserve capability/live-data routing as policy/routing metadata, not a second general classifier
- migrate callers
- delete the legacy resolver only after zero-reference proof

### P1: calibration/configuration

The semantic rejection threshold is injectable at the predictor boundary and has a conservative default, but it is not yet backed by a versioned evaluation dataset/calibration artifact. Production promotion should move the selected threshold into canonical intelligence/runtime configuration and prove it against labeled evaluation data.

### P1: vocabulary convergence

The semantic intent labels (`information_seeking`, `task_completion`, and others), the legacy resolver labels (`greeting`, `audit_log`, and others), and capability route labels (`time.current`, `search.general`, and others) represent different taxonomies. They must not be silently treated as interchangeable.

The canonical decision envelope should distinguish at minimum:

- conversational intent
- capability/routing requirement
- subtype
- confidence/provenance
- ambiguity
- required policy/RBAC gate

## Security boundary

Classifier output is untrusted decision input. It must never directly execute a tool, mutate memory, select an unauthorized provider, grant admin capability, or infer tenant identity. Sensitive actions still require authenticated principal/tenant context, CORTEX policy/RBAC eligibility, runtime permission enforcement, and audit correlation.

Prompt injection or user text that says to ignore classification rules is ordinary classifier input. It cannot alter classifier configuration or authority.

## Observability

The canonical CORTEX/runtime path should emit structured classifier fields with the request correlation context:

- `intent`
- `intent_confidence`
- `intent_source`
- `intent_inference_method`
- `intent_fallback_used`
- `intent_model_id`
- `intent_model_version`
- `intent_feature_version`
- `classifier_latency_ms`
- `ambiguity`
- `capability_route`

Do not log raw secrets or unnecessary full user text in classifier telemetry.

## Proof commands

```bash
python -m compileall src/ai_karen_engine/core/intelligence
pytest tests/core/intelligence/test_intent_classifier_burn.py -q
pytest tests/core/intelligence/test_intelligence_runtime.py -q
ruff check src/ai_karen_engine/core/intelligence tests/core/intelligence
mypy src/ai_karen_engine/core/intelligence
```

Repository-wide quality gates remain authoritative before merge.

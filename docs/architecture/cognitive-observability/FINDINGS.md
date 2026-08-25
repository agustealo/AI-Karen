# Cognitive Observability Findings

## Scan Results: Dangerous Logging Patterns

A scan of cognitive logging code (`src/ai_karen_engine/core/cortex`, `src/ai_karen_engine/core/reasoning`, `src/ai_karen_engine/core/memory`, `src/ai_karen_engine/core/neuro_recall`, `src/ai_karen_engine/core/intelligence`, `src/ai_karen_engine/core/adaptive`) for likely dangerous patterns found the following findings.

---

## TRACE-001

```text
Severity: P1
Domain: MEMORY / NLP Service
Current behavior:
src/ai_karen_engine/core/memory/signals/nlp_service_manager.py:486
logs full message content via logger.info(f"Messages: {messages}")

Missing trace:
Redaction or structured reference for message content in debug logging.

Privacy impact:
HIGH — User message content may contain PII, secrets, or sensitive data.
Debug logs may persist indefinitely and bypass redaction pipelines.

Debugging impact:
LOW — Structured reference (message count, roles, char counts) would
retain debugging value without content exposure.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-002

```text
Severity: P1
Domain: REASONING / KRO Orchestrator
Current behavior:
src/ai_karen_engine/core/reasoning/kro_orchestrator.py:1053
proposes memory text containing f"User asked about {classification.keywords}: {response_text[:100]}"

Missing trace:
Response text snippet stored directly in proposed memory without
privacy classification or redaction assessment.

Privacy impact:
HIGH — Response content snippet persisted as memory proposal.
If promoted, sensitive response content becomes retrievable memory.

Debugging impact:
NONE — This is not a logging issue but a memory content governance gap.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-003

```text
Severity: P2
Domain: REASONING / KRO Orchestrator
Current behavior:
src/ai_karen_engine/core/reasoning/kro_orchestrator.py:388
logs f"Content optimization unavailable: {e}" which may include
provider error details containing internal state.

Missing trace:
Structured error classification for optimization failures.

Privacy impact:
MEDIUM — Provider error messages may contain internal URLs, model names,
or configuration details useful to attackers.

Debugging impact:
MEDIUM — Structured error codes would improve debugging more than
raw exception strings.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-004

```text
Severity: P2
Domain: MEMORY / Agent Memory
Current behavior:
src/ai_karen_engine/core/memory/agent_memory_service.py:395
logs f"Initialization error traceback: {traceback.format_exc()}"

Missing trace:
Traceback logging at DEBUG level. While traceback is useful for debugging,
it may contain local file paths, module structure, and configuration hints.

Privacy impact:
LOW-MEDIUM — Tracebacks reveal code structure and file paths.

Debugging impact:
HIGH — Tracebacks are essential for debugging initialization failures.
This finding is informational; tracebacks should remain at DEBUG level.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-005

```text
Severity: P2
Domain: NEURO_RECALL / Client
Current behavior:
src/ai_karen_engine/core/neuro_recall/client/agent.py:162
src/ai_karen_engine/core/neuro_recall/client/agent_local_server.py:196
src/ai_karen_engine/core/neuro_recall/client/no_parametric_cbr.py:230
construct debug text from message content: f"{m['role'].upper()}: {m.get('content','')}"

Missing trace:
Message content used in debug text construction without redaction.

Privacy impact:
MEDIUM — Message content exposed in debug text. If this text is logged
or stored, user message content is exposed.

Debugging impact:
LOW — Role and content length would suffice for debugging.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-006

```text
Severity: P2
Domain: MODEL_RUNTIME / Routing
Current behavior:
src/ai_karen_engine/core/model_runtime/routing/llm_router_service.py:1988
logs with extra={"llm_router": payload} — payload contents not fully
specified in this scan but may contain request details.

Missing trace:
Structured classification of payload sensitivity before inclusion in
log extras.

Privacy impact:
MEDIUM — Payload may contain user request data, context, or preferences.

Debugging impact:
LOW — Structured payload summary would retain debugging value.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-007

```text
Severity: P2
Domain: MODEL_RUNTIME / Routing
Current behavior:
src/ai_karen_engine/core/model_runtime/routing/llm_router_service.py:1023
logs "SecretManager unavailable: %s" with exception — exception may
contain internal configuration paths.

Missing trace:
Structured error classification for SecretManager failures.

Privacy impact:
LOW-MEDIUM — Exception details may reveal internal paths or config.

Debugging impact:
LOW — Structured error codes would improve debugging.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-008

```text
Severity: P1
Domain: CORTEX / Decision
Current behavior:
BehaviorDecision exists but no canonical decision-lineage event is
guaranteed by the current observability pipeline.

Missing trace:
candidate ranking + rejection reasons + memory refs + belief refs
in a structured, queryable format.

Privacy impact:
NONE — This is a missing capability, not a data exposure.

Debugging impact:
HIGH — Without structured decision lineage, debugging "why did
Karen choose X?" requires manual log correlation across multiple
subsystems.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-009

```text
Severity: P1
Domain: MEMORY / Recall
Current behavior:
Memory recall returns memories but no structured recall lineage
event is emitted with recall scores, ranking, and influence references.

Missing trace:
recall.requested → recall.completed lineage with memory_refs,
recall_scores, rank positions, and degradation reasons.

Privacy impact:
NONE — Missing capability.

Debugging impact:
HIGH — Cannot answer "Why did Karen remember that?" or
"Why did that memory affect this answer?" without manual
correlation.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-010

```text
Severity: P1
Domain: LEARNING / Reflection
Current behavior:
ReflectionEngine and PromotionGate exist but no structured learning
lineage connects BehaviorDecision → ExecutionOutcome →
ExperienceObservation → LearningSignal → ReflectionCandidate →
PromotionDecision.

Missing trace:
end-to-end learning lineage with evidence chain.

Privacy impact:
NONE — Missing capability.

Debugging impact:
HIGH — Cannot answer "Why does this preference exist?" or
"What experiences produced this behavior?"

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-011

```text
Severity: P2
Domain: META_COGNITION
Current behavior:
No meta-cognition events are defined in the existing observability
taxonomy (RuntimeEventType). Meta-assessment, verification requirements,
loop detection, and stop recommendations have no event representation.

Missing trace:
meta.assessed, meta.verification_required, meta.loop_detected,
meta.stop_recommended events.

Privacy impact:
NONE — Missing capability.

Debugging impact:
MEDIUM — Cannot trace meta-cognitive interventions or verify
that verification requirements were enforced.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-012

```text
Severity: P2
Domain: ADAPTIVE
Current behavior:
AdaptiveRecommendation exists but no structured adaptive ranking
event links to the final behavior decision with candidate scores
and explanation codes.

Missing trace:
adaptive.ranked event with candidate set, scores, and
explanation codes linked to decision lineage.

Privacy impact:
NONE — Missing capability.

Debugging impact:
MEDIUM — Cannot trace why adaptive recommended a specific action
or how adaptive ranking influenced the decision.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-013

```text
Severity: P1
Domain: CORRELATION
Current behavior:
No causation_id exists anywhere in the codebase. The standard
pattern uses correlation_id (whole request) and request_id but
lacks event-to-event causation links.

Missing trace:
causation_id field on all cognitive events to reconstruct
actual cognitive flow.

Privacy impact:
NONE — Missing capability.

Debugging impact:
HIGH — Cannot reconstruct the causal chain of cognition.
Must rely on timestamps and hope, which fails under
concurrency and async processing.

Recommended owner:
COG-CLOSE-1

Target sprint:
Current
```

---

## TRACE-014

```text
Severity: P2
Domain: REPLAY
Current behavior:
ExecutionTrajectory exists as a replay substrate but no
CognitiveReplayManifest defines frozen input snapshots,
expected decisions, or comparison metrics.

Missing trace:
CognitiveReplayManifest, CounterfactualReplay, ReplayResult
structures.

Privacy impact:
NONE — Missing capability.

Debugging impact:
HIGH — Cannot reproduce old decisions, compare policies,
or detect behavioral drift.

Recommended owner:
COG-CLOSE-1

Target sprint:
Next
```

---

## TRACE-015

```text
Severity: P2
Domain: PRIVACY / Redaction
Current behavior:
Redaction exists at three layers (logging, observability emission,
learning record build-time) but no cognitive-specific sensitive
key list is enforced. Cognitive telemetry patterns like
memory_text, claim_text, reasoning_trace, private_reasoning
are not explicitly blocked.

Missing trace:
cognitive-specific sensitive key enforcement in redaction
subsystem.

Privacy impact:
HIGH — Without explicit cognitive sensitive keys, new cognitive
telemetry may inadvertently log forbidden content.

Debugging impact:
NONE — This is a governance gap.

Recommended owner:
COG-CONFIG-1

Target sprint:
Current
```

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| P1 | 5 | Message content in logs, response text in memory proposals, missing decision/recall/learning lineage, missing causation_id |
| P2 | 10 | Traceback logging, debug text with content, payload in extras, missing meta-cognitive/adaptive/replay events, missing cognitive redaction keys |

### Priority Actions

1. **Immediate (P1):** Remove or redact message content from `nlp_service_manager.py:486`
2. **Immediate (P1):** Add privacy classification to KRO memory proposals
3. **Immediate (P1):** Implement causation_id in observability context
4. **Immediate (P1):** Define decision lineage event emission points
5. **Next (P2):** Extend redaction subsystem with cognitive-specific sensitive keys

### Scope Compliance

This task reports findings only. No patches were made to source code.
No logger implementation changes. No runtime edits. No cognitive
logic changes.

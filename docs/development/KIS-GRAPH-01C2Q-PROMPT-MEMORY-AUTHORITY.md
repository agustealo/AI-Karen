# KIS-GRAPH-01C2Q: Model input cannot elevate request memory metadata

## Confirmed source gap

Inspected live `main` at `c384a80346d5903a5be70c270310734b7b663735`.

- `ChatRuntime._consume_resolved_memory` serializes selected `decision.cognitive_context.evidence` to `request.metadata["memory_context"]` for compatibility and telemetry.
- `ChatRuntime._assemble_prompt_with_telemetry` previously accepted `memory_context["recall"]` and, when absent, fell back to `request.metadata["memory_context"]["recall"]` without verifying its relationship to the selected, scoped `CognitiveContext`.
- `ChatRuntime._run_reasoning` likewise copied `request.metadata["memory_context"]["recall"]` directly into `ReasoningEvidence`, assigning the current tenant string rather than validating the source item.
- `RuntimeEvidenceResolver` is the already-established adapter from NeuroRecall-selected memories to scoped `CognitiveContext`. Request metadata is not the grant authority.

These direct metadata reads created a potentially exploitable promotion of untrusted input into model-visible memory when a caller could supply `request.metadata.memory_context`; the degree of exposure at any public ingress depends on upstream metadata filtering and is **not established** by this code inspection.

## Correction

`ChatRuntime._selected_memory_for_generation(request, decision)` now derives model-visible memory entries only from the existing resolved `CognitiveContext`. It rejects missing or mismatched tenant/user context, unauthorized/denied/unresolved memory source, incorrect item scope, and disabled recall. It retains the existing bounded fields and uses `decision.memory_top_k`.

Both prompt assembly and reasoning invoke the same projection. The legacy `request.metadata.memory_context` remains a downstream compatibility/telemetry copy, not a source of memory content for model generation. This is not a second memory permission or source-ACL authority. Selection and live external-source checks still belong to NeuroRecall, and runtime policy determines which sources can be used.

## Scope and proof

- `pytest tests/core/runtime/test_graph_prompt_metadata_authority.py -q`
- `pytest tests/core/runtime/test_graph_evidence_freshness_boundary.py -q`
- `pytest tests/architecture/test_context_memory_recall_authority.py -q`
- Main Quality / Backend Quality executes the adversarial metadata contract.
- Exact-head CI, review, mainline conflict audit and verified squash merge are mandatory.

The test checks the shared projection directly and statically checks both consumers, not a deployed authenticated adversarial ingress. A pre-revocation `CognitiveContext` is still a snapshot; permission changes between evidence resolution and actual model token generation remain a separate temporal invalidation problem. This slice does not claim a new ACL lease, cancel in-flight model execution, remove already disclosed content, or implement frontend-only erasure.

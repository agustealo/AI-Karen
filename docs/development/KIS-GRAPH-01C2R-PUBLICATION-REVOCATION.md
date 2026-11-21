# KIS-GRAPH-01C2R-A: Memory source identity before revocation checks

**Status:** Source candidate only. This slice does not enforce publication-time revocation.

## Owner audit

- `NeuroRecall` selects tenant/user-scoped memories and checks selected candidate lineage.
- `RuntimeEvidenceResolver` translates selected memories to `CognitiveContext.evidence`.
- `PostgresEventSource.fetch_many` rechecks current `recallable_memory_event` for explicit tenant/user/event UUID scope.
- `ChatRuntime` owns prompt, reasoning, streaming and transcript finality.
- KCM training lineage and its epoch are not a model-visible-memory authorization authority.

## Implemented

`RuntimeEvidenceResolver._canonical_memory_event_origin` derives a separate `canonical_event_origin` candidate from scoped, source-typed, internally selected memory metadata. Durable memory IDs are not confused with `memory_event.event_id`. Each supported source requires matching `tenant_id`, `user_id`, canonical record type, row ID and event ID, and normalized UUIDs. Unsupported/ephemeral/forged origins produce `None` and never receive an invented event-origin receipt.

**Security limitation:** This candidate is *not* a live consent grant. Existing prompt/reasoning consumers do not use it to grant additional evidence. Future publication revalidation must require the live ledger and fail closed for unsupported/uncertain origins. The current code does not guarantee stream revocation or withhold previously delivered model tokens.

## Tests and continuation

- `pytest tests/core/runtime/test_runtime_evidence_resolution.py -q`
- `pytest tests/core/runtime/test_graph_prompt_metadata_authority.py -q`
- Main Quality, Cognitive Proof, Chat System Burn, PostgreSQL memory proof and Production First-Boot, exact head.
- Next: verify source record revision against live ledger consent/validity, integrate before prompt dispatch, then add observed streaming and persistence revocation fences, real concurrent PostgreSQL proofs, and review before claiming authorization closure.

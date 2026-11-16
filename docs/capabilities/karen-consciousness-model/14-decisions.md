# 14 | Architecture decisions and adversarial trade-offs

[← Index](README.md) · [Previous](13-delivery-plan.md) · [Next →](15-research.md)

## ADR-KCM-001: Operational self-model, not a consciousness claim

**Decision:** "Karen Consciousness-Model" is a user-facing project label for a testable self-knowledge and capability projection. No assertion of phenomenal consciousness. **Why:** claims must map to empirical contracts and observable behavior. **Risk:** naming invites anthropomorphism; mitigate through developer/operator terminology and UI disclosures.

## ADR-KCM-002: Memory retention and training admission are separate

**Decision:** Never convert `LTM` or high importance into trainability. **Why:** subjective relevance is not label correctness, consent, distribution coverage or suitability for a learning objective. **Risk:** initially fewer training examples; accepted because accuracy and rights outrank volume.

## ADR-KCM-003: Reuse canonical architecture

**Decision:** NeuroRecall/NeuroVault/MemoryRuntimeManager remain authoritative. EchoCore curates; existing learning/model lifecycle manages artifacts; CORTEX/RuntimePolicy/ChatRuntime remain operational owners. **Rejected:** a second KCM database, orchestration/agent or model router. **Why:** DRY, tenant isolation and traceability.

## ADR-KCM-004: Self-model without neural training first

**Decision:** Project verified skills/knowledge from existing records and evaluate impact before LoRA. **Alternative:** immediate continuous fine-tuning of every experience. **Rejected because:** catastrophic forgetting, high deletion cost and weak evaluation signal.

## ADR-KCM-005: Purpose-limited datasets

**Decision:** Different candidate evaluators for Persona, procedural execution, error repair, classifier training and evaluation-only sets. **Rejected:** undifferentiated "Karen memory corpus". **Why:** correct targets and metrics differ materially.

## ADR-KCM-006: Rank after policy, select for diversity

**Decision:** Hard gates -> objective score -> coverage-aware recipe -> independent benchmark. **Rejected:** top-N importance or retrieval-frequency selection. **Why:** duplicates, popular errors and distribution collapse make rank-only solutions fragile.

## ADR-KCM-007: Parametric knowledge is not a user-memory database

**Decision:** Current user facts/preferences are retrieved from governed memory, not fitted into model weights by default. **Tradeoff:** retrieval latency vs. revocability and temporal accuracy. Reassess only with data governance and deletion proof.

## ADR-KCM-008: Source deletion fences descendants

**Decision:** Exclude source from future training immediately and trace dataset/model ancestry. Unsafe descendants cannot be auto-reactivated. **Rejected:** deletion of source files alone or unsupported blanket "model unlearned" claims. **Why:** exact parameter influence removal is not generally verifiable.

## ADR-KCM-009: Performance proof is mandatory

**Decision:** No neural-training promotion without quality, safety, cost, latency, calibration and previous-skill retention evidence versus baseline. **Rejected:** promotion because loss decreases or model sounds more like Karen.

## ADR-KCM-010: Models cannot authorize themselves

**Decision:** Capability/uncertainty signals are advisory. RuntimePolicy and privileged approval stay separate. **Rejected:** LNTG/KCM autonomous routing or policy escalation based on self-confidence.

## Open questions (resolve during P0/P1 audit; never infer current truth)

1. Which EchoCore queue and dataset manager entry points are actually live and tenant-exposed?
2. Which existing outcome-ledger and model-evaluation contracts should provide verified ground truth?
3. What source-specific consent granularity and revocation UI already exist?
4. Which scheduled worker/job system is the canonical owner for offline learning?
5. Which artifacts can be efficiently rebuilt after source deletion, and how are quantized/exported descendants tracked?
6. What are target hardware classes and strictly measurable learning objectives for first LoRA experiment?
7. Which specific capability ontology entries have sufficiently independent benchmark evidence?
8. Is any training corpus licensed/authorized for cross-user or shared-model training? Default answer remains no until proven.

These are acceptance and dependency questions, **not permission to invent services or proceed around unverified blockers**.

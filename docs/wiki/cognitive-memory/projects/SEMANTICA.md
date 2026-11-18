# Semantica | provenance, decisions and temporal truth maintenance

**Upstream:** [semantica-agi/semantica](https://github.com/semantica-agi/semantica) · **Pinned:** `4d83266ca0d7f70185906bfce7c96ec71c6ebc04` · **Version:** 0.8.0 in [manifest](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/pyproject.toml) · **License/Python:** MIT; >=3.11.5,<3.14 · **Status:** source-inspected, unbenchmarked.

## Functional mechanisms to reverse-engineer
1. [DecisionRecorder](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/context/decision_recorder.py) links decisions, evidence, policies, approvals, exceptions and provenance.
2. [TemporalTruthMaintenanceAdapter](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/reasoning/temporal_truth_maintenance.py) exposes two coordinates `valid_at` and `known_at`, snapshots and explanation of derived facts.
3. W3C PROV-O lineage and standards export, as a *representation* over approved existing evidence; **not** a claim that exported data proves external regulatory compliance.
4. Rule-based inference and explanation of supported facts, with conflict and revision handling.
5. Context graph and policy hints, but KAREN **never delegates actual RBAC or runtime execution authority** to a third-party rule engine.

## KAREN overlap and possible value
- KAREN already records memory provenance, source event IDs, temporal graph fields, runtime decisions/policies and append-only execution outcomes.
- Potential upgrade: a deterministic, read-only decision lineage query; a scoped PROV-O mapping; **known_at** snapshot consistency; explicit claims vs derived inferences.
- Audit-first rule: reconstruct only genuinely persisted decisions, not narrated model rationale.

## Dependency/deployment consequences
Even core Semantica pulls `networkx`, `rdflib`, `pyarrow`, `grpcio`, numpy, scipy, scikit-learn, Pydantic and more. Many extras add separate graph/vector/LLM infrastructures. Claims of `6,000x` node lookup must **not** be generalized to end-to-end KAREN memory retrieval without reproduced workload evidence.

## Investigation steps
- [ ] Specify canonical mapping from KAREN decision/outcome/memory IDs to PROV-O entities, activities and agents, with privacy redaction.
- [ ] Test valid-at / known-at snapshots against contradictory and backdated evidence.
- [ ] Confirm deterministic inference only over explicitly allowed facts, with lineage and transparent abstention.
- [ ] Audit erasure, policy versions and trust boundaries of exported evidence.
- [ ] R05/R06/R07/R08/R09/R10/R11/R14; measure serialization overhead separately.

**Gate:** Do not import a second decision recorder, policy engine or memory store. A small standards export or truth-maintenance technique must be justified independently.


## KCR-02B pinned code findings

[TemporalTruthMaintenanceAdapter](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/reasoning/temporal_truth_maintenance.py) supports read-only historical `query_at(valid_at, known_at)` snapshots. [DecisionRecorder](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/context/decision_recorder.py) writes to its own graph, which is incompatible with direct KAREN ownership. Native as-of semantics and read-only evidence reconstruction are research candidates. See [KCR-02B](../KCR02B_TEMPORAL_PROVENANCE.md).

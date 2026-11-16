# 09 | KCM self-model, skill maturity and knowledge boundaries

[← Index](README.md) · [Previous](08-training-and-models.md) · [Next →](10-governance-security.md)

## 1. Operational definition

KCM combines existing **Persona configuration**, **governed memory**, **verified task outcomes** and **cognitive uncertainty** into a current, evidence-backed, limited self-description. It need not be a neural network: the first release should be a deterministic/derived projection with versioned evidence links.

Three categories must remain separate:

- **Identity/persona:** configured role, tone, stable behavioral expectations. User/tenant governance owns approved overrides; prompts are versioned.
- **Knowledge and lessons:** explicit assertions with provenance, temporal validity, contradictions and attribution. Memory retains the actual records; KCM stores only rebuildable reference-based projections.
- **Capabilities and skills:** task-class performance, context, benchmark evidence, proficiency/uncertainty, known failures, last validation and confidence interval.

## 2. KCM capability card design

| Property | Description |
|---|---|
| `capability_id/version` | Stable ontology entry, versioned as taxonomy evolves |
| `scope` | Global Karen runtime, tenant or user-controlled personalization projection (never silently shared) |
| `task_signature` | Domain, tools, context complexity, input/output contracts |
| `evidence_refs` | Independent test/outcome records with result types |
| `supported_conditions` | Specific environment, model, plugin, resource and risk context |
| `attempt_count`, `verified_success_count` | Only independent, validated outcomes |
| `uncertainty` | Calibrated estimate and confidence interval, not just self-reported number |
| `last_verified_at`, `expires_at` | Staleness, dependency drift, revocation |
| `limitations` | Documented failure modes and deferral conditions |
| `learning_status` | Observed, improving, certified, stale, revoked, unknown |
| `deployment_constraints` | Readiness and policy inputs; **not** permissions |

## 3. Do not equate frequency with mastery

Suppose Karen executes 20 coding tasks: 14 verified successes, four verified failures, two unknown. These are 18 evaluated samples, not a reliable declaration that Karen is "expert" or a robust estimate across every coding environment. Maintain a conservative interval and clearly label test conditions. Some tasks are harder, repeated environments are correlated, and success may come from an external model or tool rather than the candidate skill.

A simple binomial/Wilson interval is useful only where trials are reasonably independent and comparable; otherwise use stratified benchmark reporting, calibrated per-task success estimates and explicit unknowns. Record *which model/tool configuration achieved the outcome*.

## 4. Self-knowledge vs self-authority

KCM may truthfully say:

- "I have executed and passed integration tests for this workflow on the tested environment."
- "I haven't verified this deployment on your current production configuration."
- "I have a documented correction for this failure class."

It must not say:

- "I am conscious" as an engineering fact.
- "I have permission to deploy because I am highly skilled."
- "I know this personal fact" where consent/retrieval access is unavailable.
- "My response was correct" without independent evidence.

CORTEX can consult KCM's **advisory** competence and uncertainty record; RuntimePolicy remains final permission authority.

## 5. Cross-model continuity

All providers receive the same authorized Persona contract and relevant KCM summary, with strict token/context budget; actual provider model varies. Current facts and user preferences are resolved by governed retrieval. Different models can produce coherent responses without pretending their weights are the single durable identity of Karen.

## 6. Learning from experience without changing weights

A corrected incident can immediately improve KCM via a tested procedural memory entry and error-class knowledge projection, while the neural model remains unchanged. Only once patterns produce an approved, sufficiently diverse dataset should EchoCore run offline training. This decouples responsiveness from expensive, irreversible adaptation.

## 7. KCM projection health

Expose `ready`, `stale`, `degraded`, `unavailable`, `revoked` with evidence age, last refresh receipt and missing dependency codes. UI must show uncertainty honestly. KCM unavailability must not break authorized ordinary chat.

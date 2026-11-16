# 23 | KCM-02B3A: Measured task-specific benchmark evidence

[← Index](README.md) · [Previous](22-reviewed-decision-evidence.md)

## Scope and motivation

Karen needs self-knowledge of **what has been tested**, not an invented claim of broad ability. KCM-02B3A reads a real, canonical machine-learning benchmark receipt and its exact user-scoped numeric case outcomes to describe the observed fraction correct for **one prediction task, model artifact, dataset, feature version, and test cohort**.

It does not certify a general skill, execute a capability, change CORTEX policy, select providers or train a model. KCM remains an operational evidence projection, not a new LLM or a second model registry.

## Canonical owners and reuse

| Responsibility | Existing owner | B3A change |
|---|---|---|
| Model artifact, status and current hash | MLModelRegistry | Read and independently hash current registered artifact |
| Actual benchmark execution | BenchmarkRunner, CanonicalEvaluationCorpus | Preserve existing evaluator; no parallel runner |
| Benchmark evidence issuance | EvaluationEvidenceStore | Store new exact hashed cohort membership in new receipts |
| Per-case evaluated outcomes | GovernedMLLearningEvidence and OutcomeStore | Read existing authenticated tenant/user scoped records |
| KCM task view | core/personalization/benchmark_task_assessment.py | Read-only join and descriptive confidence interval |
| Skills and execution eligibility | CapabilityRegistry, CORTEX, RuntimePolicy | **Unchanged; no permission derived from scores** |

This slice upgrades new benchmark receipts with case hashes, exact feature revision and observed correctness count. Historical receipts lacking the exact case-membership field are **not** promoted into KCM evidence, although their original promotion compatibility is retained.

## Exact join contract

A KCM report requires all of the following:

1. The current authenticated principal's tenant and user must match the exact request. Arbitrary dictionaries and expired identities fail closed.
2. The model ID must belong to the authenticated tenant's canonical registry namespace. The current model artifact, path, purpose, model version, feature revision and SHA-256 must match the benchmark receipt.
3. The receipt must have been issued by canonical EvaluationEvidenceStore for that exact model and dataset, with an explicit sample count, correctness count, and unique SHA-256 case-family reference hashes.
4. Every expected case must appear in the current scoped OutcomeStore as a held-out-evaluation outcome referencing exactly that receipt and case hash. All must agree on the task, model, feature version, correctness and no fallback.
5. The entire cohort must be present within the explicitly configured sample budget. Missing, revoked, duplicate, altered, ambiguous or cross-principal cases result in **unavailable**, not a favorable subset estimate.
6. The artifact and receipt are read again after the asynchronous outcome query; any detected drift fails closed. This is read-only freshness inspection, **not** a transactional trainer lock.

The training-data purpose and rights to reuse user data are separate checks and are NOT established by this benchmark.

## Reporting model

A successful report includes scoped task and model identity, verified artifact hash, exact receipt and dataset version, sample/correct counts, observed fraction correct and a *descriptive* 95% Wilson score interval.

The interval is explicitly labelled **assuming independent comparable trials**. Unique case IDs are not proof of independent task groups. Therefore the report always states:

- independent_trial_groups_verified = false
- production_environment_verified = false
- general_skill_certified = false
- execution_authorized = false
- training_authorized = false

A sample mean or its numerical interval does not establish general intelligence or mastery of an unrelated task. The model-specific benchmark receipt decision is also not a KCM promotion permission.

## Security, correctness and operational constraints

- The only new integrity data is hashed case-membership refs and numeric correctness, not raw examples, expected labels, prompts or model completions.
- Every report carries the precise user and tenant scope plus a deterministic diagnostic evidence digest. No results are automatically written to memory or neural weights.
- Invalid or missing model status, artifact file, receipt, case cohort, evaluation label source, feature revision or count returns unavailable. Nonexistent results must never appear as 0% accuracy.
- This is a *local registry* integrity check, not a signed external attestation against a privileged filesystem administrator. A live environment, tool/plugin version, time window and task-family independence need separate receipts before skill certification.
- The existing ML benchmark promotion gate and training RBAC are not weakened. No new public route or learner starts through KCM.

## Proof and release boundaries

The focused KCM suite creates a real isolated ML model registry with a hashed artifact, uses canonical benchmark issuance over SQLite, persists numeric cases through the canonical OutcomeStore test adapter, and checks the exact combined read. Regression cases include missing/deleted receipts, artifact mutation, mislabelled outcomes, missing/duplicate cases, model/feature drift, invalid bounds and principals, all-failed benchmarks and denial of general skill certification.

Existing KCM real PostgreSQL security gates, Main Quality, backend/frontend, cognitive execution-authority and first-boot remain mandatory for a merge.

**Next KCM-02B3B:** Add independent task-group provenance, externally reviewable held-out oracle receipts, environment/runtime and tool versions, expiry and controlled skill certification policy with preregistered error budgets. Until then Karen may say only what this exact benchmark measured.

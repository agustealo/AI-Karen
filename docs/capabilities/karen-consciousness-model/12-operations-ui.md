# 12 | Operations, observability and admin UX

[← Index](README.md) · [Previous](11-evaluation.md) · [Next →](13-delivery-plan.md)

## 1. Existing settings, no duplicate console

Add KCM information to existing Application Settings / developer learning and model lifecycle surfaces where supported. No new universal control plane. UI reads backend truth; model availability, dataset access and job readiness must come from scoped API responses.

### Suggested views (only after backend contracts exist)

- **Consciousness-Model overview:** operational status, last evidence refresh, active skills/limitations, source coverage and known unknowns; include non-sentience disclaimer in technical help.
- **Training candidates:** objective, state, reason codes, evidence quality, privacy block counts (no raw sensitive previews), reviewer queue.
- **Dataset versions:** source class counts, leakage checks, coverage, manifest SHA, license/consent status, revocation count.
- **Training runs:** actual model/adapter, artifact SHA, assigned worker, CPU/GPU usage, timestamps, true state and errors.
- **Evaluation:** baseline vs candidate, protected regressions, held-out scorecard, reviewer approval, rollback.
- **Privacy/deletion:** source revocations, affected jobs/models, remediation status, audit without exposing other tenants.

Never show a working "Train now" control without an authorized durable job API and capacity policy. Never claim "trained" from a queued candidate or mock checkpoint.

## 2. Telemetry and trace IDs

Propagate: `tenant_id`, `user_id` where appropriate, `request_id`, `correlation_id`, `source_artifact_ref`, `objective_id/version`, `policy_version`, `assessment_id`, `dataset_version_id`, `training_job_id`, `model_id/version`, `runtime_engine`, `adapter_id`, `deployment_id`, `error_type/code`, latency and status. Redact content and secrets.

Proposed metric names (non-binding until instrumentation owner review):

- `kcm_candidate_assessments_total{status,reason_code,objective}`
- `kcm_training_admission_denied_total{reason_code}`
- `kcm_verification_disagreement_rate{objective,evaluator_version}`
- `kcm_dataset_leakage_violations_total`
- `kcm_dataset_coverage_ratio{objective,task_family}`
- `kcm_training_jobs_total{status,model_family}`
- `kcm_training_job_duration_seconds`
- `kcm_model_promotion_total{status,reason}`
- `kcm_capability_evaluation_accuracy{task_family,model_version}`
- `kcm_calibration_error{task_family,model_version}`
- `kcm_revocation_fence_active_total`
- `kcm_model_rollback_total{reason}`

Avoid identifying user or tenant as a Prometheus label when it creates cardinality/privacy issues. Use trace/audit IDs for high-cardinality correlation.

## 3. Operator runbooks

**Training dependency missing:** job `failed`; do not invoke mock trainer; leave active model unchanged; display dependency/version requirement and actionable diagnostics.

**Dataset consent revoked:** stop/fence queue and active training, mark affected datasets and descendants, require rebuild/retrain/verification; keep previously unaffected chat route active.

**Artifact hash mismatch:** quarantine, prevent registration/activation, record verified corruption reason, require safe re-acquisition via existing worker.

**Quality regression:** suspend canary/promotions, revert to exact previously approved model, investigate dataset/label/adapter changes.

**Cross-tenant evidence detected:** contain immediately; revoke affected shared artifacts; audit query path, secrets and RLS session context; incident response before resume.

**KCM projection unavailable:** report `unknown/degraded` with source refresh information; don't claim the user has learned skills; keep normal chat operational.

**Model self-score conflicts with external test:** external test has authority; classify self-score as metadata, not correctness evidence.

## 4. Backpressure and resource controls

- Source enumeration paginated and scope-filtered.
- Bounded scoring/conversion concurrency with retries and dead-letter review.
- Dataset manifests constructed transactionally from validated versioned snapshots.
- Training workers have memory/disk/CPU/GPU concurrency limits, cancellation and checkpoint recovery.
- Model publication fenced by active revocation epoch and immutable manifest digest.
- Monitoring includes p95/p99 admission, training job queue wait, evaluation time and system-wide inference latency deltas.

## 5. Operations ownership

Reuse current structured logging, Prometheus, audit/security, model-download worker patterns and existing settings pages. Before adding any dashboard, inspect actual current components and APIs; prefer minimal extensions and truthful empty/degraded views. No duplicated telemetry manager or new background scheduler if the current queue works.

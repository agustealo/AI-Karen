# 04 | Memory and learning admission policy

[← Index](README.md) · [Previous](03-architecture.md) · [Next →](05-quality-selection.md)

## 1. Separate decisions

`MemoryFormationEvaluator` decides whether a signal should enter memory. EchoCore independently decides whether *an authorized, evidence-backed transformation* of an admitted record should enter an objective-specific dataset. A high `importance_score`, `access_count`, `retention_score`, `memory.quality` or `training_eligibility=ELIGIBLE` flag alone does not allow training.

**Core rule:** `training_admissible = all_hard_gates_pass AND objective_quality_pass AND dataset_distribution_accepts`.

## 2. Mandatory hard gates (in order; short circuit on failure)

1. **Identity and authorization:** authorized actor, user/tenant/workspace scope, purpose binding and source ownership; no default tenant.
2. **Data-processing consent and rights:** active permission specifically covering adaptation/training; license and contractual restrictions; personal data must not be silently pooled.
3. **Existing memory flags:** explicit `NO_TRAINING`, `NO_EXPORT`, `INELIGIBLE`, deleted, expired, quarantined or revoked always reject.
4. **Classification:** credentials/secrets/prohibited sensitivity always reject; high-sensitivity personal information defaults to ineligible even when retention is allowed; any exception needs an explicit separate legal/privacy authorization and design review.
5. **Trust and tampering:** reject poisoned/suspicious/tainted sources and prompt-injection attempts; allow unverified cases only for a separate verification queue.
6. **Evidence:** correct target label supported by a verifiable tool result, test receipt, adjudicated review or authoritative source; unverified claims cannot become positive examples.
7. **Temporal and contradiction:** superseded, contradictory or time-invalid claims cannot become unqualified current labels.
8. **Dataset lineage:** all source refs available, non-revoked and keyed to an immutable source/version; no missing-chain success.

Scores never override gates. No `force=true` from the client; exceptional operator overrides must be separately governed, auditable and unavailable for prohibited sources.

## 3. Admission states

Keep existing `ArtifactTrainingEligibility` (`ELIGIBLE`, `REVIEW`, `INELIGIBLE`) as the **upstream artifact signal**. Extend the *training candidate* owner with a lifecycle separate from memory retention:

```
DISCOVERED -> POLICY_BLOCKED
           -> NEEDS_VERIFICATION -> REVIEW -> APPROVED -> SELECTED -> CONSUMED
           -> REJECTED
APPROVED / SELECTED / CONSUMED -> REVOKED (when provenance/consent fails)
```

- **DISCOVERED:** candidate ref only; content need not be copied.
- **POLICY_BLOCKED:** prohibited by training purpose/security/privacy; may remain valid memory.
- **NEEDS_VERIFICATION:** no sound training label yet; do not select.
- **REVIEW:** verification available; independent quality or ambiguous decisions await reviewer/evaluator.
- **APPROVED:** eligible for a declared objective, not all models.
- **SELECTED:** member of one frozen dataset manifest.
- **CONSUMED:** confirmed by actual training job receipt, with checkpoint ancestry.
- **REJECTED:** documented quality/duplicate/conflict rejection.
- **REVOKED:** must be excluded from all future training and traced through descendants.

Do not mutate or repurpose memory `MemoryStatus` to represent these dataset states.

## 4. Source-class policy

| Memory source | Retain? | Potential training use | Required proof |
|---|---|---|---|
| STM chat statement | Maybe | Usually not direct | Consent, stable target, validation |
| Episodic successful tool run | Yes if worthy | Procedural positive after validation | Actual tool/status receipts and expected outcome |
| Episodic failed run | Yes | Corrective preference/rejection data | Verified failure cause and corrected target |
| LTM factual assertion | Often | Usually **retrieval only**, not parametric knowledge | Authoritative source plus strong necessity and rights |
| LTM user preference | Often | Default **retrieval only** | Explicit, training-specific consent for exceptions |
| Procedural tested workflow | Yes | Strong candidate for skill adaptation | Reproducible tests, task definition, provenance |
| Repeated memory recall | Ranked for relevance | No automatic admission | Recall is not correctness evidence |
| External article / scraped webpage | May be referenced | Normally no unless rights and verified suitability | License, provenance, injection review |
| LLM-generated synthetic example | Maybe retained as artifact | Candidate only | Independent validation and distribution controls |
| Secret, revoked or poisoned evidence | Governed quarantine/delete | **Never** | Hard rejection |

## 5. Negative learning and corrections

Do **not** fine-tune SFT on raw failures as desired completions. Preserve a failure record linked to error category and corrected, separately verified outcome. For preference training, create explicit `(context, chosen, rejected)` examples with reviewed labels. Never let the same model judge and certify its own generated target without external checking.

## 6. Temporal invalidation

A source can become invalid after approval. Use source version plus `valid_from`, `valid_until`, `verified_at`, `superseded_at`, `deletion_epoch`, `consent_version`. Any change that revokes eligibility invalidates downstream selections even when an old score is high.

## 7. No-training path

KCM self-knowledge can grow by updating durable evidence and computed capability projections with **no parametric training**. This is the default. Fine-tune only when a reproducible offline experiment shows a benefit that is not achievable through prompt/context updates or reusable procedures.

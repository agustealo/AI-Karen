# 22 | KCM-02B2: User-scoped independently reviewed decision evidence

[← Index](README.md) · [Previous](21-canonical-persona-evidence.md)

## Objective and source ownership

This slice reuses authenticated, independently reviewed runtime decision evidence as a bounded self-knowledge input **without treating reviewed decisions as general skill mastery**. It is a read-only diagnostic of verification-policy decisions.

- **Frozen decisions and feature snapshots:** canonical runtime TrajectoryStore.
- **Reviewer authorization and issuance:** existing VerificationReviewWorkflow and AuthenticatedPrincipal. A reviewer cannot review their own decision.
- **Durable matching receipts:** existing OutcomeStore intelligence.ml rows. An independently judged reward and verification-need label are recorded separately.
- **Canonical revalidation:** GovernedVerificationReviewEvidence.require_persisted_reviews compares both receipts against each frozen decision, hashes, review identity, policy lineage, tenant/user and allowable action/risk contract.
- **KCM projection:** core/personalization/reviewed_decision_evidence.py delegates to the canonical verifier; no new evidence store, duplicate reviewer registry or decision router.

**User ownership is mandatory.** The tenant-wide canonical SelfModel has no user_id, so this is a separate diagnostic view, not a user-history field added to that tenant-wide object. Never aggregate private evaluations to a global Karen skill without a separately governed privacy/assessment process.

## Read-only reporting contract

For a bounded, authenticated and fully verified decision cohort, KCM-02B2 can report the number of reviewed decisions, paired receipt count, distinct reviewer count, *reviewer-judged mean reward*, independently judged verification-need count, and a tenant/user-scoped SHA-256 diagnostic evidence fingerprint.

This is not accuracy, task success rate, calibrated proficiency, general coding skill, model readiness, or a training label. Scores describe those exact reviewed **shadow verification-policy decisions** only. Repeated cases may be correlated and must not masquerade as independent benchmarks.

Every report has scope=user, capability_certified=false, policy_activated=false, execution_authorized=false and training_authorized=false. A report is either fully verified or unavailable; no partial favorable scores on missing evidence.

## Fail-closed security

1. The trusted runtime must supply a real authenticated subject principal matching the exact tenant and user. A caller-supplied dictionary, expired principal or mismatched owner is refused.
2. KCM copies the frozen typed observations before awaiting evidence retrieval. The canonical verifier checks their identifiers and decision-time probabilities against immutable, independently issued review receipts.
3. Both records for every decision are fetched from the canonical scoped OutcomeStore. Changed reward, stale/missing receipt, modified feature hash, mismatched review origin, duplicate ID, high-risk class or unsupported action blocks the report.
4. An explicit 1–500-case budget prevents unbounded review retrieval. Empty/malformed studies are unavailable.
5. No raw prompts, memory content, reviewer narratives or sensitive source payloads appear in the returned report or fingerprint. Diagnostic logs contain only counts, scope and failure type.
6. The only verifier is Karen's existing review reconciler. There is no caller-provided success summary, fake fallback, training promotion or permission bypass.

## Current limitations and next slice

This is a trusted runtime composition module, not a new API/UI or an activated general capability model. Existing reviewer labels measure a narrow verification-policy choice, not general Karen task capability. Source deletion removes canonical outcome rows and subsequent reads fail closed, but corrections/withdrawal of independent reviews and model-to-evidence lineage require separate governance before any training.

The dedicated KCM CI gate covers actual issuance and reconciliation of scoped review receipts using the existing OutcomeStore contract, plus tampering, identity violations, duplicate cases, deletion, high risk, invalid budgets and non-authorizing output. Database review authority/RLS tests remain owned by the existing Intelligence evaluation suite.

**Next KCM-02B3:** Define genuine task-signature skill assessment with independent held-out oracles, bounded conditions, registered capability/runtime versions, reviewer authorization, revocation and statistically justified proficiency. Until proven, Karen must say that general skill proficiency is not verified.

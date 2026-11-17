# 27 | KCM-02B3C2B: Review withdrawal and revocation-aware consumption

[← Developer wiki](README.md) · [Previous](26-reviewed-curated-oracle-observations.md)

## Scope and established owners

This is a governed *restrictive withdrawal* of an exact, previously confirmed
KCM curated-oracle reviewer acknowledgment. It does **not** authorize any
additional evaluation, model promotion, training, execution, skill certification
or cross-tenant read. `GovernedCuratedOracleReviewEvidence` remains the narrow
adapter under canonical ML evaluation; the existing tenant-scoped,
FORCE-RLS `OutcomeStore` remains the only durable receipt owner.

The original proposal + confirmation pair and verified numeric benchmark
evidence are not overwritten or deleted by withdrawal.

## Issuance contract

Only a current authenticated reviewer, in the original tenant and with
`intelligence.ml.benchmark_oracle_review`, may withdraw **their own** currently
confirmed exact cohort. The subject principal must also be authenticated and
match the exact tenant/user. An unrelated reviewer, self-reviewer, revoked
session, wrong-tenant principal or already withdrawn cohort fails closed.

The adapter reuses the original canonical registry/artifact, benchmark SQLite
receipt, exact source/conditions, canonical OutcomeStore numeric cases and
reviewer-confirmation pair. No user-supplied success assertion, score or
alternate authority can substitute for those sources.

The withdrawal is a third deterministic, append-only outcome receipt:
`kcm_curated_oracle_reviewer_withdrawal_v1`. Its metadata contains only
the subject-scoped exact benchmark receipt and model IDs, original reviewer,
original confirmed review ID, snapshot SHA-256, revocation timestamp,
`reason_code=reviewer_withdrawal` and `review_withdrawn=true`. The canonical
store's strict schema rejects unexpected fields, invalid identities,
unsupported reasons and malformed timestamps.

Duplicate withdrawal is not permitted. A failed or uncertain write is never
reported as completed without a scoped readback. If the write committed but
the caller's session expired afterward, the revocation remains restrictive.

## Revocation-aware read contract

`inspect_review` now retrieves **proposal, confirmation and withdrawal**
by exact owner/tenant IDs. A withdrawal, even an invalid one with the exact
revocation ID, suppresses favorable acknowledgment. It repeats the withdrawal
check after the final awaited numeric-cohort verification to detect a
withdrawal committed during that read. The current model/dataset/feature/
artifact hashes and benchmark freshness rules remain unchanged.

This is in-process application consistency, not an atomic distributed
authorization lease. The returned observation is advisory only; a future
consumer must perform its own fenced authorization check. An append-only
withdrawal cannot itself promote a model or enable a tool.

## Explicit limitations

- Self-withdrawal currently requires a *current, otherwise consumable* review.
  A separate governed host revocation flow is needed for expired, deleted or
  inaccessible source records. Such observations already read as unavailable.
- The design permits only the original authorized reviewer to withdraw their
  own acknowledgment. Administrative overturn, conflict adjudication, review
  corrections and audit export require a separately authorized contract.
- No cryptographic independent ground truth, blind task-group separation,
  training-corpus inventory, off-host runtime attestation or general-skill
  certification has been established by acknowledgment or withdrawal.
- Immutable hashes and local SQLite/PostgreSQL writes do not defend against
  privileged modification of the host or database. Per-tenant RLS, current
  source revalidation and independent audit remain mandatory.

## Proof requirements

The existing dedicated KCM test suite and real PostgreSQL review workflow
must verify: exact reviewer admission, append-only proposed/confirmed/withdrawn
rows, cross-principal refusal, duplicate withdrawal, unchanged numeric
benchmarks, final-read concurrent withdrawal, malformed withdrawal schema,
real FORCE RLS, and consumption denial after withdrawal.

**Release gate:** exact-head GitHub Actions + code review + independent
PostgreSQL proof. Keep C2B stacked on C2A until C2A's reviewed release is
merged and the changed files are reconciled against live `main`.

**Next KCM evidence boundary:** independent author/reviewer identities,
held-out training/evaluation split provenance, independent oracle adjudication,
per-case source revocation and environment attestation. None of these is
implied by a curator's group label or a reviewer acknowledgment.

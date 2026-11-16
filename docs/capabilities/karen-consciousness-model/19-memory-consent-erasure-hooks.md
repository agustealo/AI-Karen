# 19 | KCM-01D2B: Canonical memory, consent and erasure invalidation

[← Index](README.md) · [Previous](18-durable-revocation-lineage.md)

**State:** Implementation PR. This is a transactional revocation safeguard,
not a training capability. KCM's training_authorized database constraints
remain false, and no weights can be trained or published through this path.

## 1. Ownership and source of truth

- **Memory content and lifecycle:** NeuroVault and public.memory_event.
- **Consent grant/withdrawal:** Existing public.consent_scope and canonical
  memory control repository. KCM is **not** a second consent registry.
- **Privacy-erasure lifecycle:** Existing public.privacy_requests.
- **Learning governance:** One kcm_internal source-revocation function and
  KCM's previously merged owner-scoped epoch/lineage records.
- **Training admission:** EchoCore, still requiring independent rights and
  target-verification evidence, never merely a valid LTM or consent scope.

The implementation uses narrowly scoped PostgreSQL triggers on canonical
source tables instead of additional application-level deletion callbacks.
This captures alternate writers that use the same tables and commits KCM
revocations **atomically with** the authoritative memory/consent mutation.

## 2. Trigger coverage

| Canonical change | KCM effect |
|---|---|
| Memory event tombstone / valid_to change | Revoke the affected event revision and increment owner epoch |
| Memory event hard deletion | Revoke that source and block reintroduction |
| Memory event payload, source hash, sensitivity or consent modification | Revoke the old source revision |
| New event superseding a previous memory | Resolve the parent assertion ID to its event revision and revoke that source |
| Consent scope first inserted as denied, granted to denied, revoked_at set or scope identity changed | Invalidate owner KCM lineage and revoke all currently quarantined sources |
| Granted consent scope deleted | Invalidate KCM owner scope and its enrolled sources |
| Privacy erasure request enters in_progress or completed | Invalidate owner lineage before data removal is finalized |

Consent revocation is conservative. An absent scope is treated as granted
by current memory recall and NeuroVault checks, so its first denied INSERT
is also a genuine withdrawal. Arbitrarily named memory consent scopes
can govern source content; a withdrawal therefore fences **all currently
quarantined KCM lineage for that owner**, not solely records with a training
prefix. This may generate extra revocation epochs but cannot grant training.

The source-revocation helper only creates derivative source records for
**enrolled KCM source revisions**. An unrelated memory update does not bloat
KCM governance or change its deletion epoch. Scope-wide consent/privacy
withdrawals still advance the epoch even if no lineage is enrolled.

A source with an invalid or legacy payload digest cannot be registered in a
KCM dataset; the source trigger does not misrepresent it as a valid SHA-256
training revision.

## 3. Atomicity and authorization

All hooks execute inside the original PostgreSQL transaction. If KCM
revocation storage fails for a provisioned source, **the original memory
mutation also rolls back**; neither layer may silently claim success.

Both the source-revocation helper and the owner-wide invalidation helper
serialize writes through the same kcm_training_scope_state owner row.
Already revoked source versions remain blocked from new dataset registration
by the existing anti-replay trigger.

No API, model, worker or browser principal receives permissions on
kcm_internal routines. The security-definer functions are pinned to
pg_catalog and refer to canonical relations with explicit schema names.
Triggers derive tenant/user directly from the authoritative OLD/NEW records;
they do not trust user-supplied training metadata or a model response.

If KCM has no provisioned scope row, KCM epoch reads remain unavailable and
all existing evidence preflight requests fail closed. Canonical memory
operations may continue; KCM adoption is not required for ordinary memory.

## 4. What is not yet solved

- Rights/licenses and ground-truth outcome verification remain **independent
  authorities**, not new booleans derived from memory retention or runtime
  success.
- No trainer-start or checkpoint-promotion lease exists. The two epoch reads
  in dataset preflight are not an atomic training lock.
- No model-to-source ancestry exists beyond quarantined dataset membership;
  erasing a memory from PostgreSQL cannot unlearn trained weights.
- Deletion in external datasets/connected tools needs a separate audited
  propagation contract. This migration hooks only Karen's **canonical**
  memory/consent/privacy SQL paths.
- Legacy data held exclusively outside the canonical ledger is not covered.
- No production KCM training installation or fine-tune is authorized.

## 5. Proof

The dedicated KCM GitHub Actions gate creates two fresh, isolated databases:
karen_kcm_test for the original scope/RLS lineage proof and
karen_kcm_lifecycle_test for the lifecycle-mutation proof.

The latter verifies actual PostgreSQL revocation on tombstone, hard deletion,
payload alteration, assertion-ID supersession, first denied consent INSERT,
consent withdrawal and privacy erasure,
owner isolation, anti-replay, RLS access, and rollback when the revocation
write is deliberately made to fail.

**Next:** real rights/license and independently reviewed outcome receipts,
then an atomic training-start and checkpoint-promotion fence that reuses
these immutable source and epoch contracts. Training stays disabled until
these acceptance requirements pass.

# Backup & Recovery Specification

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Runbook
**Owner:** Operations

---

## 1. PostgreSQL

- Daily backup
- PITR enabled
- Migration metadata preserved
- Restore test quarterly

## 2. Storage

Separate:
- Object inventory
- Object backup
- Checksum verification
- Restore process

## 3. Redis

No durable-truth requirement.
Redis recovery means cache warmup and STM/session degradation/recreation, not data restore.

## 4. Recovery Steps

1. Verify Supabase project health
2. Restore database from latest backup
3. Replay WAL for PITR if required
4. Restore Storage objects from inventory
5. Verify checksums
6. Warm Redis cache
7. Validate application health endpoints

## 5. Governed-memory recovery admission (open acceptance boundary)

A backup snapshot predating a committed consent withdrawal or memory retirement
cannot independently prove current authorization. Do not admit a recovered
memory authority to consumer traffic until recovery has been reconciled against
a trusted revocation cutoff that was not rolled back with the snapshot.

The guarded PostgreSQL restore command checks the selected archive digest,
refuses targets containing existing application relations, and restores in a
single transaction. Use an exclusively offline, fresh target; the catalog
preflight is not a lease against concurrent access or proof of network isolation.
A successful command reports staging only, never consumer admission.

The disposable backup/restore regression deliberately demonstrates the unsafe
pre-reconciliation state: an older snapshot can restore retired/revoked memory
and replay receipts. Passing this diagnostic is NOT proof of recovery safety.
Trusted cutoff reconciliation and automated admission remain outstanding.
Operators must treat missing or unverifiable reconciliation evidence as a
recovery hold, not as permission to serve governed memory.

Required acceptance:

- Restore a pre-revocation backup into an isolated disposable database after
  committing a deletion or consent withdrawal. Reconcile against an independently
  retained authoritative cutoff (or verified WAL recovery through that cutoff).
- Deny recall, export, stale idempotent replay and retired identity reuse.
- Verify that missing, older, incomplete or unverifiable recovery evidence
  cannot authorize service admission. Preserve tenant isolation and audit records.
- Rebuild Redis and other derived projections from currently authorized sources;
  do not use restored Redis snapshots as durable memory truth.
- Exercise a delayed producer after revocation as well as independent readers.
  Read-side denial does not establish physical erasure of stale cached bytes.

No claim of physical erasure of historical backups or atomic database-to-wire
authorization is made. This is an operator hold and acceptance specification,
not an implemented automated recovery admission gate.

## 6. References

- `docs/operations/platform-health.md`
- `docs/operations/storage-integrity.md`

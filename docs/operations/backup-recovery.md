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
Backup and restore require PostgreSQL clients matching the connected server major;
set KAREN_POSTGRES_BIN_DIR to an installed matching client directory if needed.
The fresh-target restore does not use DROP/clean options. Major-version upgrades
require a separate verified migration procedure.

The disposable backup/restore regression deliberately demonstrates the unsafe
pre-reconciliation state: an older snapshot can restore retired/revoked memory
and replay receipts. Passing this diagnostic is NOT proof of recovery safety.
Trusted cutoff reconciliation and automated admission remain outstanding.
Operators must treat missing or unverifiable reconciliation evidence as a
recovery hold, not as permission to serve governed memory.

### Physical WAL cutoff evidence

While the original authoritative primary is still accessible, externally fence
and drain **all** writers (including background jobs and administrative mutation
paths), then collect a minimum replay-position receipt:

```bash
DATABASE_URL='postgresql://authoritative-primary...' \\
CONFIRM_SOURCE_FENCED='I_HAVE_FENCED_SOURCE_WRITERS' \\
  bash scripts/deploy/database-recovery-cutoff.sh
```

Retain the emitted JSON in a trusted recovery inventory outside the cluster
and backup rollback domain, using an authenticated, append-only or immutable
storage policy. The command does not implement that storage policy or fence
writers itself. The confirmation token is an operator assertion, not proof.
Capture must happen after the last accepted mutation and before source loss;
if later writes are permitted, the receipt is no longer the final cutoff.
Missing permissions, unavailable primary or unflushed WAL leave recovery held.

The receipt binds the observed system identifier, database name and OID,
server major, WAL timeline, required insertion LSN and covering flush LSN.
A timestamp is descriptive, not a freshness authority. A logical restore can
have the same cluster identity and a greater LSN while containing older rows.
Do not use a receipt captured from a restored database, compare LSN alone,
or treat this command's exit status as admission. Independently authenticated
receipt retrieval, timeline/physical replay proof, source fencing, complete
WAL availability and service admission enforcement remain separate requirements.
Managed-service PITR must supply equivalent trusted lineage evidence; support
and privileges are not assumed.

### Paused standby replay observation

The same-timeline streaming recovery diagnostic accepts a receipt and the
expected digest obtained independently from the trusted recovery inventory:

```bash
RECOVERY_DATABASE_URL='postgresql://isolated-standby...' \
RECOVERY_CUTOFF_FILE='/secure/recovery/final-cutoff.json' \
RECOVERY_CUTOFF_SHA256='<digest from trusted inventory>' \
  python3 scripts/deploy/database-recovery-replay.py
```

The command rejects absent or malformed evidence, digest mismatches, a primary
or promoted target, mismatched cluster/database identity, mismatched timeline,
an unpaused target, or receive/replay positions below the required cutoff.
It requires a live same-timeline streaming receiver and a paused read-only
standby; archive-only recovery, timeline transitions, and managed PITR need a
separate verified evidence path. A digest is not a signature or freshness
proof: the expected digest must come from the independently authenticated final
inventory, not from the same untrusted file. A matching observation is not
exclusive custody, a lease against promotion or replay resume, verification of
the upstream's trust, proof of immutable retention, or permission to serve.
The JSON output explicitly reports admission_verified=false.

The disposable CI diagnostic creates a physical standby from the synthetic
test cluster, pauses it before revocation, tests denial at the old replay
position, then resumes and pauses after the cutoff and checks the committed
deletion and consent rows. No production database is cloned or promoted.
Automated runtime admission remains outstanding.

### Authenticated final cutoff manifest

For signed evidence, the independent recovery authority signs the exact UTF-8
JSON manifest bytes using an externally held Ed25519 signing key. The manifest
has exactly these fields: schema_version (1), evidence_type
(karen_final_recovery_cutoff), deployment, recovery_epoch, cutoff_sha256.
Deployment and epoch are nonempty ASCII identifiers (letters, digits,
underscore, dot or hyphen; maximum 128 characters, starting with a letter or
digit). The epoch is unique to a recovery incident. The authority must retain
the exact signed manifest, detached signature and receipt in independent
immutable storage and pin the final manifest digest in its trusted inventory.
An earlier valid signature is not proof of finality.

The existing replay observer accepts six additional environment values:
RECOVERY_MANIFEST_FILE, RECOVERY_MANIFEST_SIGNATURE_FILE (raw 64-byte signature),
RECOVERY_TRUSTED_PUBLIC_KEY_FILE (44-byte Ed25519 SPKI DER),
RECOVERY_EXPECTED_DEPLOYMENT, RECOVERY_EXPECTED_EPOCH and
RECOVERY_EXPECTED_MANIFEST_SHA256. The public key and expected identifiers/digest
must come from trusted recovery configuration outside the restored database.
OpenSSL with Ed25519 support is required. The caller still supplies the
receipt file and its expected digest. Partial signed configuration fails
closed; no fallback to digest-only mode is allowed in that case. Digest-only
mode remains an explicitly unsigned diagnostic, not admission. Successful
signed verification reports signed_manifest_verified=true, but
admission_verified=false.

The verifier does not provision immutable storage, manage signing keys,
discover the final epoch, certify source fencing, or authorize promotion.
Production inventory and trusted key custody require separate infrastructure
acceptance; the CI test signs synthetic evidence using disposable keys only.

### Explicit application recovery hold

Set KAREN_DATABASE_RECOVERY_MODE=hold in the actual process environment
before starting the canonical ASGI application against recovery infrastructure.
The base Compose API environment explicitly forwards this setting, including
an invalid empty value, through the production overlay that resets env_file.
For hosted Render deployments set the process environment explicitly; no
existing hosted service setting is changed by this repository contract.
The application factory and lifespan reject startup before router wiring or
service acquisition. The legacy package ASGI module also rejects held import
and factory construction, and both existing server startup functions deny
before service acquisition. Normal-mode legacy routes remain unchanged while
their references and replacement contracts are audited. The canonical PostgreSQL engine rejects initialization,
factory access and new pool checkouts. Invalid mode values also deny.
The default normal preserves existing non-recovery deployments; the absence
of a hold is not proof that a database has been safely recovered. This is not
a live distributed kill switch: stop/drain all processes, fence credentials
and network access, and keep independent workers, direct database clients
and legacy entrypoints isolated. Existing checked-out connections are not
revoked by this check. No signed diagnostic automatically clears the hold.
Do not set normal for a recovered target until the separate admission protocol
is independently verified. No global enforcement claim is made.

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

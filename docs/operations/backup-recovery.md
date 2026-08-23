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

## 5. References

- `docs/operations/platform-health.md`
- `docs/operations/storage-integrity.md`

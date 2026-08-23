# Storage Integrity / Reconciliation Specification

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Design
**Owner:** Platform + Operations

---

## 1. Detection

- DB metadata with missing object
- Object without metadata
- Checksum mismatch
- Stuck PENDING
- Stuck DELETE_PENDING

## 2. Output Actions

- Repair
- Retry
- Quarantine
- Delete orphan
- Operator alert

## 3. Reuse

Before implementing a new service, audit existing:
- `database_consistency_validator.py`

## 4. Schedule

Run reconciliation as a durable queue job (`artifact.reconcile`) on a 10-minute cron.

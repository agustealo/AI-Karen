# Functions & Trigger Governance

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Standard
**Owner:** Architecture Team

---

## 1. Functions May Own

- Atomic data operations
- Query helpers
- Aggregation
- Secure tenant-scoped primitives
- Queue enqueue wrapper

## 2. Triggers May Own

- updated_at
- Audit append
- Search-vector derivation
- Semantic Broadcast
- Queue/outbox enqueue

## 3. Forbidden

- CORTEX
- Provider selection
- Prompt construction
- Agents
- Tool calls
- Network-heavy workflows
- Complex business orchestration

## 4. Rationale

PostgreSQL logic should stay deterministic, fast, and free from runtime concerns.

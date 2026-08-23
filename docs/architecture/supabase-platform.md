# Supabase Platform Ownership Contract

**Version:** 1.0
**Date:** 2026-08-23
**Status:** Canonical
**Owner:** Architecture Team

---

## 1. Purpose

This document defines exactly what Supabase may and may not own in the KAREN runtime.

Supabase is a **platform**, not an authority. KAREN remains the runtime, policy, and orchestration authority.

## 2. Ownership Matrix

| Capability               | Owner                |
| ------------------------ | -------------------- |
| Durable relational truth | Supabase Postgres    |
| Vectors                  | Postgres + pgvector  |
| Lexical search           | PostgreSQL FTS       |
| Tenant DB isolation      | RLS                  |
| Binary artifacts         | Supabase Storage     |
| Browser realtime         | Supabase Broadcast   |
| Online/viewing awareness | Supabase Presence    |
| Durable jobs             | Supabase Queues/pgmq |
| Scheduled DB maintenance | pg_cron              |
| Preview DB environments  | Supabase Branching   |
| PITR/backups             | Supabase platform    |
| STM/cache/locks          | Redis                |
| Prompt/runtime decisions | KAREN                |
| Provider routing         | KAREN                |
| Agent orchestration      | KAREN                |
| Memory semantics         | KAREN                |
| Plugin execution         | KAREN                |
| RBAC decisions           | KAREN                |

## 3. Forbidden Behaviors

Supabase **MUST NOT** become identity authority by accident.
Edge Functions **MUST NOT** own ChatRuntime.
Realtime **MUST NOT** become business truth.
Presence **MUST NOT** store workflow state.
Postgres Changes **MUST NOT** become the default realtime transport.
Vector Buckets **MUST NOT** replace pgvector as Tier-1.
Analytics Buckets **MUST NOT** become Tier-1 warehouse.

## 4. Runtime Boundaries

```
KAREN Runtime
├── intelligence
├── orchestration
├── provider/model routing
├── agents
├── memory policy
├── plugins
└── persistence decisions

Supabase
├── Postgres
├── pgvector
├── FTS
├── RLS
├── Broadcast
├── Presence
├── Storage
├── Queues
├── Cron
├── branching
├── backups/PITR
└── deterministic DB-side helpers

Redis
├── STM
├── cache
├── locks
├── leases
├── rate limits
└── transient runtime coordination
```

## 5. References

- `docs/architecture/supabase-realtime-authorization.md`
- `docs/architecture/supabase-jwt-bridge.md`
- `docs/architecture/supabase-feature-rejection.md`

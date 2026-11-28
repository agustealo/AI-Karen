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

## 6. Optional private CA for Storage transport

The default platform behavior is unchanged when neither configuration value is
set. An operator may explicitly supply both
`KAREN_SUPABASE_STORAGE_TLS_ORIGIN` (the exact HTTPS project origin) and
`KAREN_SUPABASE_STORAGE_TLS_CA_FILE` (absolute path to a PEM CA bundle).
Incomplete, invalid or mismatched configuration disables Storage initialization;
there is no insecure retry. The private CA trust context is initialized once
and shared by SDK signing and bounded reads. It trusts only the supplied CA
bundle, retains certificate and hostname checks, and does not inherit proxies
or ambient CA variables. The custom SDK HTTP client rejects foreign destinations
and redirects and is closed on platform reset. Keep the CA bundle read-only
and private deployment configuration outside the checkout.

This contract is Storage HTTP transport only. It does not certify Realtime
WebSockets or establish Docker gateway provenance. The isolated acceptance
overlay, certificate identity continuity and real Supabase signing/range read
must be independently verified before local consumer acceptance. No HTTP
allowlist expansion or TLS bypass is authorized.

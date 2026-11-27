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

## Disposable local Storage HTTPS acceptance

Docker owner-text and Content Intelligence modes require the existing native
Supabase Kong HTTPS listener, published on the canonical local API port from
`supabase/config.toml`. On a compatible legacy Supabase CLI, configure
`[api.tls]` with a certificate covering `host.docker.internal`, then start
the local stack using the installed CLI's supported configuration. Do not
change shared config or restart an existing database automatically. Supply
`KCARD_LOCAL_STORAGE_URL=https://host.docker.internal:<configured-port>`,
`KCARD_LOCAL_STORAGE_SECRET_KEY` (local fixtures only), and
`KCARD_LOCAL_STORAGE_CA_FILE` (absolute external public CA bundle) together
in private operator configuration. Never commit a CA private key or secret.
The existing deployment runner copies only the public CA into private state
and binds it read-only into the isolated API. The canonical verifier checks
the actual Kong 8443 mapping, exact CA bytes, and a hostname-verified TLS
handshake from the API container at every Storage acceptance checkpoint.
The peer leaf digest must also match the identified Kong public certificate.
The recorded peer certificate and CA digests must remain unchanged.
Standalone host-loopback HTTP proof remains separate; generic Explorer
does not certify Storage. Unsupported local gateway layouts fail closed.
Real SDK signing and browser acceptance remain required.

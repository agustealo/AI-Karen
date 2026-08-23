# Supabase Project Scaffold

## Local Start

```bash
supabase init
supabase start
```

## Branch Workflow

Feature branches get Supabase preview branches.
Never clone production user data into preview automatically.

## Migration Authority Handoff

Database-core migrations are owned by the active data-spine developer.
This parallel sprint only adds scaffolding and contracts.

## Seed Policy

Use synthetic fixture data in preview environments.

## Storage Bucket Setup

Tier-1 buckets:
- artifacts-private
- exports-private
- public-assets

## Realtime Setup

Realtime is enabled in config.toml.
Broadcast is the default production path.
Postgres Changes requires explicit architecture approval.

## RLS Test Policy

Run RLS tests against preview branches before merging.

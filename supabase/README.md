# Supabase / PostgreSQL Data Authority

`supabase/migrations/` is the canonical schema migration authority for AI Karen's primary PostgreSQL data spine.

## Local Start

```bash
supabase init
supabase start
```

## Branch Workflow

Feature branches get Supabase preview branches.
Never clone production user data into preview automatically.
Use synthetic fixture data in preview environments.

## Production Migration Contract

Production schema changes are applied only from `supabase/migrations/` through the guarded operator command:

```bash
DATABASE_URL='postgresql://...' \
  bash scripts/deploy/migrate-production-database.sh
```

The production migration command must create and checksum a PostgreSQL backup before `supabase db push` is allowed to run.
Application startup must not silently mutate production schema.

## Backup Contract

Create a primary PostgreSQL backup with:

```bash
DATABASE_URL='postgresql://...' \
  bash scripts/deploy/database-backup.sh
```

The command writes a PostgreSQL custom-format dump, SHA-256 checksum, and non-secret metadata beneath `KAREN_BACKUP_ROOT` or `./backups/postgres`.

This command covers the primary PostgreSQL store only. Redis, Milvus, Elasticsearch, object storage, model artifacts, and external services are separate recovery domains and must not be represented as protected by this backup.

## Restore Contract

Restore is destructive and requires a separate target URL plus an explicit confirmation token:

```bash
RESTORE_DATABASE_URL='postgresql://recovery-target...' \
BACKUP_FILE='./backups/postgres/<timestamp>/ai-karen-postgres.dump' \
CONFIRM_RESTORE='I_UNDERSTAND_THIS_IS_DESTRUCTIVE' \
  bash scripts/deploy/database-restore.sh
```

Verify restore behavior against an isolated recovery or staging database before using the procedure for an incident.

## Storage Bucket Setup

Tier-1 buckets:
- artifacts-private
- exports-private
- public-assets

## Realtime Setup

Realtime is enabled in `config.toml`.
Broadcast is the default production path.
Postgres Changes requires explicit architecture approval.

## RLS Test Policy

Run RLS tests against preview branches before merging.
Tenant-scoping and RLS migrations are production security boundaries and must not be bypassed during recovery.

## Production Baseline 2026-08

The pre-production construction history was consolidated into six ordered baseline stages on 2026-08-27.
The baseline preserves the execution order and SQL semantics of the prior migration chain while removing repair-file sprawl.
The previous files remain available in Git history and are not executable migration authorities.

Primary PostgreSQL schema evolution has exactly one authority: `supabase/migrations/`.
Application runtime, Docker init scripts, ORM metadata, and server subpackages must not apply or invent primary PostgreSQL schema changes.
After this baseline cut, applied production history is immutable and all changes are new forward-only migrations.

# AI KAREN Database Layer

The database layer provides runtime persistence access for AI KAREN. It does **not** own primary PostgreSQL schema evolution.

## Primary PostgreSQL authority

`supabase/migrations/` is the only primary PostgreSQL schema-evolution authority.

Production schema changes are applied by deployment tooling through:

```bash
DATABASE_URL='postgresql://...' \
  bash scripts/deploy/migrate-production-database.sh
```

That command creates and verifies a PostgreSQL backup before applying Supabase migrations. Application startup, ORM metadata, Docker initialization, plugins, routes, and services must not create, alter, or drop primary PostgreSQL schema.

After the 2026-08 production baseline, applied migration history is immutable. Every schema change is a new forward-only migration. See `docs/database/BASELINE_2026_08.md`.

## Runtime responsibilities

The runtime database package owns:

- PostgreSQL connection and session lifecycle
- tenant-scoped data access
- SQLAlchemy persistence mappings
- transaction handling
- read-only schema and migration health inspection
- database-specific repository support

It does not own migration execution.

## Storage domains

### PostgreSQL

Primary relational data spine. Schema authority is `supabase/migrations/`.

### Redis

Bounded session/state/cache responsibilities. Redis recovery and lifecycle are separate from PostgreSQL migrations.

### DuckDB

Local analytics/projection storage. DuckDB has an explicitly separate schema domain and must not be confused with primary PostgreSQL authority.

### Vector/search stores

Milvus, Elasticsearch, and other retrieval stores have separate lifecycle and recovery contracts. The PostgreSQL backup procedure does not claim to protect them.

## ORM models

SQLAlchemy models describe persistence mappings and relationships. They are not migration definitions. Do not use `metadata.create_all()`, `metadata.drop_all()`, or runtime DDL to evolve the primary PostgreSQL schema.

When a model requires a schema change:

1. add a forward migration under `supabase/migrations/`;
2. update the mapping;
3. add tenant/RLS/constraint/index proof where applicable;
4. run the Production Database Baseline Contract and recovery tests.

## Tenant isolation

Tenant-owned records must preserve explicit tenant scope through repository and database boundaries. RLS migrations are security boundaries, not convenience filters. Do not replace database enforcement with UI-only or route-only checks.

## Migration status

`services/database/migration_validator.py` may read Supabase migration state for health/operations reporting. It must remain read-only and must never apply or manufacture migrations.

## Backup and restore

Canonical operator scripts:

- `scripts/deploy/database-backup.sh`
- `scripts/deploy/migrate-production-database.sh`
- `scripts/deploy/database-restore.sh`

Restore is destructive and requires explicit confirmation. See `supabase/README.md` for the operator contract.

## Proof

Database-related changes should run at minimum:

```bash
pytest tests/architecture/test_production_database_baseline_contract.py -q
pytest tests/architecture/test_production_data_recovery_contract.py -q
python -m compileall src
bash -n scripts/deploy/database-backup.sh
bash -n scripts/deploy/database-restore.sh
bash -n scripts/deploy/migrate-production-database.sh
```

Production rule: **one PostgreSQL schema authority, forward-only migrations, runtime read-only with respect to schema evolution.**

# Retired database backend audit: DuckDB

Status: **DuckDB retired from active KAREN runtime**. This document records
the 2026-11-19 cleanup scope, not a claim that every historical document or
database artifact has been migrated or deleted.

## Canonical ownership

- **PostgreSQL / Supabase:** authoritative durable records, auth, tenant data,
  transactional receipts, memory persistence, and governed recovery.
  Existing migrations, RLS, schema, and production DB configuration remain.
- **Redis:** live worker leases, bounded STM/session/cache state. Redis is not
  a replacement for durable PostgreSQL.
- **No active DuckDB runtime dependency:** root `requirements.txt` explicitly
  classifies DuckDB among retired databases, and does not install the package.
  No DuckDB deployment or data migration is introduced by this cleanup.

## Removed legacy runtime references

| Path | Before | After | Risk |
| --- | --- | --- | --- |
| `src/ai_karen_engine/server/config.py` | Requires `KARI_DUCKDB_PASSWORD` even when DuckDB is retired | Removes this key from `required_env_vars`; leaves all other secrets and database requirements intact | Low |
| `docker-compose.yml` | Exports `KARI_ENABLE_DUCKDB=true` to the API | No longer advertises an obsolete local analytics engine | Low |

These were misplaced/dead configuration flags, not persisted schema or
provider implementations. There is no replacement DuckDB implementation:
analytics must use approved PostgreSQL read/query services or explicitly
reviewed derived computation, never an unapproved parallel authoritative DB.

## Cleanup boundary

This change **does not delete** PostgreSQL or Redis configuration aliases,
production secrets, historical migrations, snapshots, auth/RBAC policies,
audit receipts, or data files. A name appearing in old documentation is not
proof of a live database. Historical records are left intact until separately
verified against active imports, deployment jobs, backup/recovery requirements,
and data-retention policy. Do not add DuckDB back to the startup secret list.

## Verification

```bash
# Repository-wide reference audit on a full checkout:
git grep -n -i -E 'duckdb|KARI_ENABLE_DUCKDB|KARI_DUCKDB_PASSWORD' -- \
  ':!tests/architecture/test_retired_duckdb_runtime_contract.py' \
  ':!docs/architecture/RETIRED_DATABASE_BACKENDS.md'

python -m compileall src
pytest -q tests/architecture/test_retired_duckdb_runtime_contract.py
pytest tests/ -q
ruff check src tests
docker compose config
```

The first command is a review step: distinguish remaining historical mentions
from reachable runtime consumers before any additional deletion. For Compose,
use an approved secret-backed deployment environment; do not bypass required
Postgres credentials to manufacture a passing config. The CI suite is the
source of exact-head proof. Live Render recovery additionally requires the
remaining PostgreSQL, Redis, and cryptographic environment variables to be
provisioned securely, then a genuinely healthy `/ready` response.

**Do not claim the hosted API is healthy merely because the obsolete DuckDB
requirement was removed.** The earlier Render logs also identified missing
canonical database connections and required cryptographic keys.

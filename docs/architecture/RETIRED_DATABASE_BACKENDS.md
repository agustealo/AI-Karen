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

## Follow-up removal: Render and abandoned DuckDB adapter

The initial runtime cleanup did not cover every deployment owner. The subsequent
reference audit found these additional paths and classified them as follows:

| Path | Classification | Disposition | Risk |
| --- | --- | --- | --- |
| `deploy/render/render.yaml` | Dead secret generation | Remove retired secret; retain canonical DB, Redis, other secrets and health configuration | Low |
| `scripts/deploy/inspect_render_beta_environment.py` | Dead protected-secret inventory item | Remove retired key, preserve all active environment checks | Low |
| `scripts/ci/production-first-boot-smoke.sh` | Obsolete test-only secret injection | Delete only the DuckDB variable, retain real PostgreSQL/Redis and auth test setup | Low |
| `scripts/ci/presentation-self-contained-capture.sh` | Obsolete test-only secret injection | Delete only the DuckDB variable, retain protected test setup | Low |
| `src/ai_karen_engine/storage/adapters/duckdb.py` | Replaced, unsafe legacy profile/role/memory store | Delete adapter (no DuckDB runtime dependency); PostgreSQL is canonical | Medium: requires reference proof |

The retired adapter offered direct local profile and role writes with no
tenant isolation or authoritative RBAC audit, and depended on a Python library
already absent from active requirements. This is **not** a migration or deletion
of user data, historical file contents, or backup artifacts. Before removing
any historical DuckDB files from a real host, independently verify lineage,
retention and the PostgreSQL replacement records.

The architecture test uses actual regex matches (not literal backslash
patterns) over all first-party `src`, deployment scripts, CI scripts and
Render Blueprint files. It rejects DuckDB imports, adapter references and
the retired environment flags. The full exact-head architecture suite must
pass before merge. A stale import is a stop condition, not a reason to
reintroduce DuckDB or bypass the test.

Proof:
```bash
python -m pytest -q tests/architecture/test_retired_duckdb_runtime_contract.py
python -m pytest -q tests/architecture/test_render_beta_blueprint_contract.py
git grep -n -E 'DuckDBClient|storage[./]adapters[./]duckdb|KARI_DUCKDB_PASSWORD|KARI_ENABLE_DUCKDB' -- src scripts deploy
```

Do not treat this source cleanup as a live Render backend repair. Render still
requires securely configured PostgreSQL, Redis and cryptographic secrets, a
reviewed exact-head backend deployment, and real `/ready` proof.

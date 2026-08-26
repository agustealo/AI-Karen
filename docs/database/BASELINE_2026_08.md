# AI KAREN PostgreSQL Production Baseline — 2026-08

## Authority

`supabase/migrations/` is the only primary PostgreSQL schema-evolution authority.

## Baseline mapping

| New baseline stage | Previous pre-production history |
| --- | --- |
| `01_core_persona_runtime` | `agui_chat_core`, `persona_persistence`, `chat_runtime_control_plane` |
| `02_auth_profile_finalization` | `fix_auth_user_schema`, `populate_missing_profile_fields` |
| `03_memory` | `memory_ledger`, `memory_convergence` |
| `04_tenant_security` | `conversation_tenant_scoping`, `row_level_security` |
| `05_schema_security_finalization` | `schema_corrections`, `embedding_provenance`, `rls_expansion` |
| `06_auth_refresh_history` | `auth_refresh_token_history` |
| `07_identity_vault` | Existing Identity Vault ORM schema moved under canonical migration authority |

The baseline intentionally preserves prior SQL ordering and semantics. Git history is the archive for the superseded migration files.

## Retired competing authorities

- `src/ai_karen_engine/database/migrations/`
- `src/ai_karen_engine/database/migration_manager.py`
- `src/ai_karen_engine/database/migration/`
- `docker/database/migrations/postgres/`
- `docker/database/scripts/migration-manager.py`
- `server/chat/migrations/`
- `server/migrations/`

DuckDB and other non-PostgreSQL stores remain separate recovery/schema domains and must be explicitly scoped as such.

## Production rule

Once this baseline is applied to a persistent environment, these files are immutable. Every subsequent schema change is a new forward-only Supabase migration. Application startup never runs schema migration or ORM `create_all`/`drop_all` for the primary PostgreSQL spine.

## Recovery

Production migration execution remains guarded by `scripts/deploy/migrate-production-database.sh`, which creates and verifies a PostgreSQL backup before applying migrations. Destructive recovery uses `scripts/deploy/database-restore.sh`.

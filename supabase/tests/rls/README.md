# RLS Proof Tests

Row-Level Security (RLS) proof tests verify that tenant isolation is enforced
at the database layer. These tests require a running PostgreSQL instance with
the migrations from `../migrations/` applied.

## Required Proofs

1. **Tenant A cannot read Tenant B's data** — cross-tenant SELECT returns 0 rows
2. **Tenant A cannot write to Tenant B's data** — cross-tenant INSERT/UPDATE/DELETE is denied
3. **Anonymous access denied** — queries without tenant context return no data
4. **Service role bypass is intentional** — backend operations using the
   Supabase service role can access all rows (for admin/audit operations)
5. **`app.tenant_id` session config** — the `async_transaction_scope(tenant_id)`
   helper correctly sets `app.tenant_id` for RLS policy evaluation
6. **`DatabaseSettings.rls_enforced` defaults to True**

## Running

```bash
# Requires DATABASE_URL pointing to a test database with migrations applied
pytest supabase/tests/rls/ -v
```

## Architecture

Three-layer tenant defense:

```
Runtime/API
    auth + tenant context

Repository
    explicit tenant-scoped operations

PostgreSQL RLS
    hard database enforcement
```

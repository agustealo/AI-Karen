-- Migrated from database/migrations/013_rls_expansion.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 013_rls_expansion.sql
-- Description: Extend RLS to remaining tenant-owned tables.
-- Fixes: auth_users, auth_providers, roles, api_keys, webhooks,
--        usage_counters, audit_log, llm_requests

-- ============================================================================
-- 1. auth_users
-- ============================================================================
ALTER TABLE auth_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS auth_users_tenant_isolation ON auth_users;
CREATE POLICY auth_users_tenant_isolation ON auth_users
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 2. auth_providers
-- ============================================================================
ALTER TABLE auth_providers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS auth_providers_tenant_isolation ON auth_providers;
CREATE POLICY auth_providers_tenant_isolation ON auth_providers
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 3. roles
-- ============================================================================
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS roles_tenant_isolation ON roles;
CREATE POLICY roles_tenant_isolation ON roles
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 4. api_keys
-- ============================================================================
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS api_keys_tenant_isolation ON api_keys;
CREATE POLICY api_keys_tenant_isolation ON api_keys
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 5. webhooks
-- ============================================================================
ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS webhooks_tenant_isolation ON webhooks;
CREATE POLICY webhooks_tenant_isolation ON webhooks
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 6. usage_counters
-- ============================================================================
ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS usage_counters_tenant_isolation ON usage_counters;
CREATE POLICY usage_counters_tenant_isolation ON usage_counters
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 7. audit_log
-- ============================================================================
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_log_tenant_isolation ON audit_log;
CREATE POLICY audit_log_tenant_isolation ON audit_log
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- 8. llm_requests
-- ============================================================================
ALTER TABLE llm_requests ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS llm_requests_tenant_isolation ON llm_requests;
CREATE POLICY llm_requests_tenant_isolation ON llm_requests
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

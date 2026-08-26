-- AI KAREN production baseline migration
-- Consolidated pre-production history. Future production changes are forward-only.
-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.


-- ============================================================================
-- BASELINE SOURCE: 20260823100000_schema_corrections.sql
-- ============================================================================

﻿-- Migrated from database/migrations/011_schema_corrections.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 011_schema_corrections.sql
-- Description: Correct schema contract mismatches from 008/009/010.
-- Fixes: content_tsv type, tenant/user ID types, redundant embedding_vector,
--         RLS fail-closed semantics, and broken backfill assumptions.
--
-- Do NOT amend 008/009/010. This is a corrective migration.

-- ============================================================================
-- 1. Fix memory_items.content_tsv: must be TSVECTOR, not TEXT
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memory_items' AND column_name = 'content_tsv'
    ) THEN
        ALTER TABLE memory_items DROP COLUMN content_tsv;
    END IF;
END $$;

ALTER TABLE memory_items
    ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

-- ============================================================================
-- 2. Fix memory_items.tenant_id / user_id: TEXT -> UUID (fail-closed)
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memory_items'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE memory_items
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memory_items'
          AND column_name = 'user_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE memory_items
            ALTER COLUMN user_id TYPE UUID
            USING user_id::uuid;
    END IF;
END $$;

-- ============================================================================
-- 3. Drop redundant embedding_vector; canonical vector column is embeddings
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memory_items' AND column_name = 'embedding_vector'
    ) THEN
        ALTER TABLE memory_items DROP COLUMN embedding_vector;
    END IF;
END $$;

-- ============================================================================
-- 4. Fix auth_users.tenant_id: TEXT -> UUID (fail-closed)
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'auth_users'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE auth_users
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

-- ============================================================================
-- 5. Fix remaining auth-layer tenant/user IDs: TEXT -> UUID
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'auth_providers'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE auth_providers
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'roles'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE roles
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'api_keys'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE api_keys
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'files'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE files
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'webhooks'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE webhooks
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'usage_counters'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE usage_counters
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'usage_counters'
          AND column_name = 'user_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE usage_counters
            ALTER COLUMN user_id TYPE UUID
            USING user_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_log'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE audit_log
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'audit_log'
          AND column_name = 'user_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE audit_log
            ALTER COLUMN user_id TYPE UUID
            USING user_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'llm_requests'
          AND column_name = 'tenant_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE llm_requests
            ALTER COLUMN tenant_id TYPE UUID
            USING tenant_id::uuid;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'llm_requests'
          AND column_name = 'user_id'
          AND data_type = 'text'
    ) THEN
        ALTER TABLE llm_requests
            ALTER COLUMN user_id TYPE UUID
            USING user_id::uuid;
    END IF;
END $$;

-- ============================================================================
-- 6. Recreate FTS index on corrected content_tsv
-- ============================================================================
DROP INDEX IF EXISTS idx_memory_items_content_tsv;
CREATE INDEX IF NOT EXISTS idx_memory_items_content_tsv
    ON memory_items USING GIN (content_tsv);

-- ============================================================================
-- 7. Recreate HNSW index on canonical embeddings column
-- ============================================================================
DROP INDEX IF EXISTS idx_memory_items_embedding_vector;
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_vector
    ON memory_items
    USING hnsw (embeddings vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- 8. Drop broken RLS policies from 010 and recreate with fail-closed + WITH CHECK
-- ============================================================================

-- memory_items
DROP POLICY IF EXISTS memory_items_tenant_isolation ON memory_items;
CREATE POLICY memory_items_tenant_isolation ON memory_items
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- conversations
DROP POLICY IF EXISTS conversations_tenant_isolation ON conversations;
CREATE POLICY conversations_tenant_isolation ON conversations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- messages (no tenant_id column; derive from conversation)
DROP POLICY IF EXISTS messages_tenant_isolation ON messages;
CREATE POLICY messages_tenant_isolation ON messages
    FOR ALL
    USING (
        conversation_id IN (
            SELECT conversation_id FROM conversations
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    )
    WITH CHECK (
        conversation_id IN (
            SELECT conversation_id FROM conversations
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    );

-- files
DROP POLICY IF EXISTS files_tenant_isolation ON files;
CREATE POLICY files_tenant_isolation ON files
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_event (ledger)
DROP POLICY IF EXISTS memory_event_tenant_isolation ON memory_event;
CREATE POLICY memory_event_tenant_isolation ON memory_event
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_assertion (ledger)
DROP POLICY IF EXISTS memory_assertion_tenant_isolation ON memory_assertion;
CREATE POLICY memory_assertion_tenant_isolation ON memory_assertion
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ============================================================================
-- BASELINE SOURCE: 20260823110000_embedding_provenance.sql
-- ============================================================================

﻿-- Migrated from database/migrations/012_embedding_provenance.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 012_embedding_provenance.sql
-- Description: Add embedding provenance tracking to memory_items.
-- Columns: embedding_model, embedding_version, embedding_dimension, embedded_at

-- ============================================================================
-- 1. Add embedding provenance columns
-- ============================================================================
ALTER TABLE memory_items
    ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255),
    ADD COLUMN IF NOT EXISTS embedding_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP;

-- ============================================================================
-- 2. Backfill existing rows with safe defaults
-- ============================================================================
UPDATE memory_items
SET
    embedding_model = COALESCE(metadata->>'embedding_model', 'unknown'),
    embedding_version = COALESCE(metadata->>'embedding_version', 'v1'),
    embedding_dimension = COALESCE((metadata->>'embedding_dimension')::INTEGER, 384),
    embedded_at = COALESCE(created_at, NOW())
WHERE embedding_model IS NULL;

-- ============================================================================
-- 3. Create index for model/version queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_provenance
    ON memory_items (embedding_model, embedding_version, tenant_id);

-- ============================================================================
-- BASELINE SOURCE: 20260823120000_rls_expansion.sql
-- ============================================================================

﻿-- Migrated from database/migrations/013_rls_expansion.sql (preserving original lineage)
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

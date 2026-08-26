-- AI KAREN production baseline migration
-- Consolidated pre-production history. Future production changes are forward-only.
-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.


-- ============================================================================
-- BASELINE SOURCE: 20260823080000_conversation_tenant_scoping.sql
-- ============================================================================

﻿-- Migrated from database/migrations/009_conversation_tenant_scoping.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 009_conversation_tenant_scoping.sql
-- Description: Add tenant_id to conversations and chat_conversations for canonical multi-tenancy.

-- Add tenant_id to conversations table (derive from user -> tenant lookup)
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

-- Backfill tenant_id from auth_users
UPDATE conversations c
SET tenant_id = au.tenant_id
FROM auth_users au
WHERE c.user_id = au.user_id
  AND c.tenant_id IS NULL;

-- Make tenant_id NOT NULL after backfill
ALTER TABLE conversations
    ALTER COLUMN tenant_id SET NOT NULL;

-- Indexes for tenant-scoped conversation queries
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user
    ON conversations(tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_active
    ON conversations(tenant_id, is_active);

-- Add tenant_id to chat_conversations table
ALTER TABLE chat_conversations
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

-- Backfill tenant_id from auth_users
UPDATE chat_conversations cc
SET tenant_id = au.tenant_id
FROM auth_users au
WHERE cc.user_id = au.user_id
  AND cc.tenant_id IS NULL;

-- Make tenant_id NOT NULL after backfill
ALTER TABLE chat_conversations
    ALTER COLUMN tenant_id SET NOT NULL;

-- Indexes for tenant-scoped chat conversation queries
CREATE INDEX IF NOT EXISTS idx_chat_conversations_tenant_user
    ON chat_conversations(tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_tenant_archived
    ON chat_conversations(tenant_id, is_archived);

-- ============================================================================
-- BASELINE SOURCE: 20260823090000_row_level_security.sql
-- ============================================================================

﻿-- Migrated from database/migrations/010_row_level_security.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: 010_row_level_security.sql
-- Description: Enable Row Level Security on canonical tables for defense-in-depth tenant isolation.

-- Enable RLS on memory_items
ALTER TABLE memory_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY memory_items_tenant_isolation ON memory_items
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Enable RLS on conversations
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

CREATE POLICY conversations_tenant_isolation ON conversations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Enable RLS on messages
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY messages_tenant_isolation ON messages
    FOR ALL
    USING (
        conversation_id IN (
            SELECT conversation_id FROM conversations
            WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
        )
    );

-- Enable RLS on files
ALTER TABLE files ENABLE ROW LEVEL SECURITY;

CREATE POLICY files_tenant_isolation ON files
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Enable RLS on memory_event (ledger)
ALTER TABLE memory_event ENABLE ROW LEVEL SECURITY;

CREATE POLICY memory_event_tenant_isolation ON memory_event
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

-- Enable RLS on memory_assertion (ledger)
ALTER TABLE memory_assertion ENABLE ROW LEVEL SECURITY;

CREATE POLICY memory_assertion_tenant_isolation ON memory_assertion
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

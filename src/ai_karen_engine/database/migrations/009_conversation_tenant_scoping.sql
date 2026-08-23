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

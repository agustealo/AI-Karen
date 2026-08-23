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

-- Enable RLS and create policies for all tenant-owned tables

-- memory_items
ALTER TABLE memory_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_items_tenant_isolation ON memory_items;
CREATE POLICY memory_items_tenant_isolation ON memory_items
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- conversations
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS conversations_tenant_isolation ON conversations;
CREATE POLICY conversations_tenant_isolation ON conversations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- messages (no tenant_id column; derive from conversation)
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
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
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS files_tenant_isolation ON files;
CREATE POLICY files_tenant_isolation ON files
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_event (ledger)
ALTER TABLE memory_event ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_event_tenant_isolation ON memory_event;
CREATE POLICY memory_event_tenant_isolation ON memory_event
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_assertion (ledger)
ALTER TABLE memory_assertion ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_assertion_tenant_isolation ON memory_assertion;
CREATE POLICY memory_assertion_tenant_isolation ON memory_assertion
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- auth_users
ALTER TABLE auth_users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_users_tenant_isolation ON auth_users;
CREATE POLICY auth_users_tenant_isolation ON auth_users
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_relation
ALTER TABLE memory_relation ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_relation_tenant_isolation ON memory_relation;
CREATE POLICY memory_relation_tenant_isolation ON memory_relation
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- profile_fact
ALTER TABLE profile_fact ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS profile_fact_tenant_isolation ON profile_fact;
CREATE POLICY profile_fact_tenant_isolation ON profile_fact
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- memory_episode
ALTER TABLE memory_episode ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_episode_tenant_isolation ON memory_episode;
CREATE POLICY memory_episode_tenant_isolation ON memory_episode
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
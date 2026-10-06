-- Core tables from migration 01
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    tenant_id UUID,
    title TEXT,
    conversation_metadata JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    session_id TEXT,
    ui_context JSONB DEFAULT '{}'::jsonb,
    ai_insights JSONB DEFAULT '{}'::jsonb,
    user_settings JSONB DEFAULT '{}'::jsonb,
    summary TEXT,
    tags TEXT[],
    last_ai_response_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_created ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_active ON conversations(is_active);
CREATE INDEX IF NOT EXISTS idx_conversation_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversation_tags ON conversations(tags);
CREATE INDEX IF NOT EXISTS idx_conversation_user_session ON conversations(user_id, session_id);

CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_metadata JSONB DEFAULT '{}'::jsonb,
    function_call JSONB,
    function_response JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_convo_time ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS message_tools (
    message_tool_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments JSONB,
    result JSONB,
    latency_ms INT,
    status TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_message_tools_message ON message_tools(message_id);

CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    source TEXT,
    scope TEXT,
    kind TEXT,
    content TEXT,
    embeddings VECTOR(768),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    expires_at TIMESTAMP,
    importance FLOAT DEFAULT 0.5,
    confidence FLOAT DEFAULT 1.0,
    source_type VARCHAR(100) DEFAULT 'system',
    source_ref VARCHAR(255),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding_model VARCHAR(255),
    embedding_version VARCHAR(64),
    embedding_dimension INTEGER,
    embedded_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_scope_kind ON memory_items(scope, kind);
CREATE INDEX IF NOT EXISTS idx_memory_items_tenant_user ON memory_items(tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_items_content_tsv ON memory_items USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_memory_items_embeddings_hnsw ON memory_items USING hnsw (embeddings vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding_provenance ON memory_items (embedding_model, embedding_version, tenant_id);

CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    tenant_id UUID,
    owner_user_id UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    name TEXT,
    mime_type TEXT,
    bytes BIGINT,
    storage_uri TEXT,
    sha256 TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    tenant_id UUID,
    url TEXT NOT NULL,
    secret TEXT,
    events JSONB NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS marketplace_extensions (
    extension_id TEXT PRIMARY KEY,
    latest_version TEXT,
    title TEXT,
    author TEXT,
    summary TEXT,
    metadata JSONB,
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS installed_extensions (
    id BIGSERIAL PRIMARY KEY,
    extension_id TEXT REFERENCES marketplace_extensions(extension_id) ON DELETE SET NULL,
    version TEXT,
    installed_by UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    installed_at TIMESTAMP DEFAULT now(),
    source TEXT,
    directory TEXT
);

CREATE TABLE IF NOT EXISTS usage_counters (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    metric TEXT NOT NULL,
    value BIGINT NOT NULL,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_counter_metric_window ON usage_counters(metric, window_start);

CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    limit_name TEXT,
    window_sec INT,
    max_count INT,
    current_count INT,
    window_reset TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_providers (
    provider_id TEXT PRIMARY KEY,
    tenant_id UUID,
    type TEXT NOT NULL,
    config JSONB NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_identities (
    identity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth_users(user_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES auth_providers(provider_id),
    provider_user TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    role_id TEXT PRIMARY KEY,
    tenant_id UUID,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id TEXT REFERENCES roles(role_id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    scope TEXT,
    PRIMARY KEY (role_id, permission, scope)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_tenant_name ON roles(tenant_id, name);

CREATE TABLE IF NOT EXISTS api_keys (
    key_id TEXT PRIMARY KEY,
    tenant_id UUID,
    user_id UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    hashed_key TEXT NOT NULL,
    name TEXT,
    scopes JSONB NOT NULL,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    expires_at TIMESTAMP,
    UNIQUE (hashed_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_hashed_key ON api_keys(hashed_key);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id BIGSERIAL PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    actor_type TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    ip_address TEXT,
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    provider_type VARCHAR(50) NOT NULL,
    encrypted_config BYTEA NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id UUID REFERENCES llm_providers(id) ON DELETE SET NULL,
    provider_name VARCHAR(100) NOT NULL,
    model VARCHAR(100),
    tenant_id UUID,
    user_id UUID,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost NUMERIC(10,4),
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_provider_time ON llm_requests(provider_name, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_requests_tenant_time ON llm_requests(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS hooks (
    hook_id TEXT PRIMARY KEY,
    hook_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_name TEXT,
    priority INT DEFAULT 50,
    enabled BOOLEAN DEFAULT TRUE,
    conditions JSONB,
    registered_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hook_exec_stats (
    id BIGSERIAL PRIMARY KEY,
    hook_type TEXT,
    source_name TEXT,
    executions BIGINT DEFAULT 0,
    successes BIGINT DEFAULT 0,
    errors BIGINT DEFAULT 0,
    timeouts BIGINT DEFAULT 0,
    avg_duration_ms INT DEFAULT 0,
    window_start TIMESTAMP,
    window_end TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extensions (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    category TEXT,
    capabilities JSONB,
    directory TEXT,
    status TEXT NOT NULL,
    error_msg TEXT,
    loaded_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS extension_usage (
    id BIGSERIAL PRIMARY KEY,
    name TEXT REFERENCES extensions(name) ON DELETE CASCADE,
    memory_mb NUMERIC(10,2),
    cpu_percent NUMERIC(5,2),
    disk_mb NUMERIC(12,2),
    network_sent BIGINT,
    network_recv BIGINT,
    uptime_seconds BIGINT,
    sampled_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ext_usage_name_time ON extension_usage(name, sampled_at DESC);
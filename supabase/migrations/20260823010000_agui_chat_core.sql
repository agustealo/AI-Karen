-- Migrated from database/migrations/001_agui_chat_core.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Initial schema for AG-UI + Copilot-ready chat core

CREATE TABLE auth_users (
  user_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email             TEXT UNIQUE NOT NULL,
  full_name         TEXT,
  password_hash     TEXT,                -- null if SSO-only
  tenant_id         TEXT,                -- multi-tenant
  roles             JSONB NOT NULL,      -- ["admin","user",...]
  preferences       JSONB DEFAULT '{}'::jsonb,
  is_verified       BOOLEAN DEFAULT FALSE,
  is_active         BOOLEAN DEFAULT TRUE,
  two_factor_enabled BOOLEAN DEFAULT FALSE,
  two_factor_secret TEXT,
  created_at        TIMESTAMP NOT NULL DEFAULT now(),
  updated_at        TIMESTAMP NOT NULL DEFAULT now(),
  last_login_at     TIMESTAMP,
  failed_login_attempts INT DEFAULT 0,
  locked_until      TIMESTAMP
);

CREATE INDEX idx_auth_users_tenant_email ON auth_users(tenant_id, email);

CREATE TABLE auth_sessions (
  session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES auth_users(user_id) ON DELETE CASCADE,
  access_token        TEXT NOT NULL,
  refresh_token       TEXT NOT NULL,
  expires_in          INT NOT NULL,                 -- seconds
  created_at          TIMESTAMP NOT NULL DEFAULT now(),
  last_accessed       TIMESTAMP NOT NULL DEFAULT now(),
  ip_address          TEXT,
  user_agent          TEXT,
  device_fingerprint  TEXT,
  geolocation         JSONB,
  risk_score          NUMERIC(5,2) DEFAULT 0,
  security_flags      JSONB DEFAULT '[]'::jsonb,
  is_active           BOOLEAN DEFAULT TRUE,
  invalidated_at      TIMESTAMP,
  invalidation_reason TEXT
);

CREATE INDEX idx_auth_sessions_user_active ON auth_sessions(user_id, is_active);
CREATE INDEX idx_auth_sessions_last_accessed ON auth_sessions(last_accessed DESC);

CREATE TABLE auth_providers (
  provider_id   TEXT PRIMARY KEY,        -- "google","github","saml-foo"
  tenant_id     TEXT,
  type          TEXT NOT NULL,           -- oauth|saml|oidc
  config        JSONB NOT NULL,
  metadata      JSONB DEFAULT '{}'::jsonb,
  enabled       BOOLEAN DEFAULT TRUE,
  created_at    TIMESTAMP DEFAULT now(),
  updated_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE user_identities (
  identity_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth_users(user_id) ON DELETE CASCADE,
  provider_id   TEXT NOT NULL REFERENCES auth_providers(provider_id),
  provider_user TEXT NOT NULL,           -- sub / external id
  metadata      JSONB,
  created_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE roles (
  role_id     TEXT PRIMARY KEY,
  tenant_id   TEXT,
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMP DEFAULT now(),
  UNIQUE (tenant_id, name)
);

CREATE TABLE role_permissions (
  role_id     TEXT REFERENCES roles(role_id) ON DELETE CASCADE,
  permission  TEXT NOT NULL,             -- "chat:read", "extensions:manage"
  scope       TEXT,                      -- optional resource scope
  PRIMARY KEY (role_id, permission, scope)
);

CREATE TABLE api_keys (
  key_id       TEXT PRIMARY KEY,
  tenant_id    TEXT,
  user_id      UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
  hashed_key   TEXT NOT NULL,            -- store a hash only
  name         TEXT,
  scopes       JSONB NOT NULL,           -- ["chat:write","files:read"]
  last_used_at TIMESTAMP,
  created_at   TIMESTAMP DEFAULT now(),
  expires_at   TIMESTAMP,
  UNIQUE (hashed_key)
);

CREATE UNIQUE INDEX idx_roles_tenant_name ON roles(tenant_id, name);
CREATE UNIQUE INDEX idx_api_keys_hashed_key ON api_keys(hashed_key);

CREATE TABLE audit_log (
  event_id      BIGSERIAL PRIMARY KEY,
  tenant_id     TEXT,
  user_id       TEXT,
  actor_type    TEXT,                    -- user|system|extension
  action        TEXT NOT NULL,
  resource_type TEXT,
  resource_id   TEXT,
  ip_address    TEXT,
  user_agent    TEXT,
  details       JSONB,
  created_at    TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);

CREATE TABLE conversations (
  conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
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

CREATE INDEX idx_conversation_user ON conversations(user_id);
CREATE INDEX idx_conversation_created ON conversations(created_at);
CREATE INDEX idx_conversation_active ON conversations(is_active);
CREATE INDEX idx_conversation_session ON conversations(session_id);
CREATE INDEX idx_conversation_tags ON conversations(tags);
CREATE INDEX idx_conversation_user_session ON conversations(user_id, session_id);

CREATE TABLE messages (
  message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  message_metadata JSONB DEFAULT '{}'::jsonb,
  function_call JSONB,
  function_response JSONB,
  created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_messages_convo_time ON messages(conversation_id, created_at);

CREATE TABLE message_tools (
  message_tool_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  arguments JSONB,
  result JSONB,
  latency_ms INT,
  status TEXT,
  created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_message_tools_message ON message_tools(message_id);

CREATE TABLE memory_items (
  memory_id     TEXT PRIMARY KEY,
  tenant_id     TEXT,
  user_id       TEXT,
  source        TEXT,                        -- convo|file|profile|plugin
  scope         TEXT,                        -- global|convo:<id>|user:<id>
  kind          TEXT,                        -- fact|task|profile|doc_chunk
  content       TEXT,
  embeddings    VECTOR(768),                 -- if using pgvector
  metadata      JSONB,
  created_at    TIMESTAMP DEFAULT now(),
  updated_at    TIMESTAMP DEFAULT now(),
  expires_at    TIMESTAMP
);

CREATE INDEX idx_memory_scope_kind ON memory_items(scope, kind);

CREATE TABLE extensions (
  name         TEXT PRIMARY KEY,
  version      TEXT NOT NULL,
  category     TEXT,
  capabilities JSONB,
  directory    TEXT,
  status       TEXT NOT NULL,                -- active|error|unloading|...
  error_msg    TEXT,
  loaded_at    TIMESTAMP,
  updated_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE extension_usage (
  id              BIGSERIAL PRIMARY KEY,
  name            TEXT REFERENCES extensions(name) ON DELETE CASCADE,
  memory_mb       NUMERIC(10,2),
  cpu_percent     NUMERIC(5,2),
  disk_mb         NUMERIC(12,2),
  network_sent    BIGINT,
  network_recv    BIGINT,
  uptime_seconds  BIGINT,
  sampled_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_ext_usage_name_time ON extension_usage(name, sampled_at DESC);

CREATE TABLE hooks (
  hook_id      TEXT PRIMARY KEY,
  hook_type    TEXT NOT NULL,
  source_type  TEXT NOT NULL,              -- extension|plugin|system
  source_name  TEXT,
  priority     INT DEFAULT 50,
  enabled      BOOLEAN DEFAULT TRUE,
  conditions   JSONB,
  registered_at TIMESTAMP DEFAULT now()
);

CREATE TABLE hook_exec_stats (
  id           BIGSERIAL PRIMARY KEY,
  hook_type    TEXT,
  source_name  TEXT,
  executions   BIGINT DEFAULT 0,
  successes    BIGINT DEFAULT 0,
  errors       BIGINT DEFAULT 0,
  timeouts     BIGINT DEFAULT 0,
  avg_duration_ms INT DEFAULT 0,
  window_start TIMESTAMP,
  window_end   TIMESTAMP
);

CREATE TABLE llm_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) UNIQUE NOT NULL,
  provider_type VARCHAR(50) NOT NULL,
  encrypted_config BYTEA NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE llm_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id UUID REFERENCES llm_providers(id) ON DELETE SET NULL,
  provider_name VARCHAR(100) NOT NULL,
  model VARCHAR(100),
  tenant_id VARCHAR(255),
  user_id VARCHAR(255),
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  total_tokens INTEGER,
  cost NUMERIC(10,4),
  latency_ms INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_llm_requests_provider_time ON llm_requests(provider_name, created_at);
CREATE INDEX idx_llm_requests_tenant_time ON llm_requests(tenant_id, created_at);

CREATE TABLE files (
  file_id       TEXT PRIMARY KEY,
  tenant_id     TEXT,
  owner_user_id UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
  name          TEXT,
  mime_type     TEXT,
  bytes         BIGINT,
  storage_uri   TEXT,                      -- s3://..., file://...
  sha256        TEXT,
  metadata      JSONB,
  created_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE webhooks (
  webhook_id   TEXT PRIMARY KEY,
  tenant_id    TEXT,
  url          TEXT NOT NULL,
  secret       TEXT,                       -- HMAC secret (hashed at rest)
  events       JSONB NOT NULL,             -- ["convo.created","message.created"]
  enabled      BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMP DEFAULT now(),
  updated_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE marketplace_extensions (
  extension_id  TEXT PRIMARY KEY,
  latest_version TEXT,
  title         TEXT,
  author        TEXT,
  summary       TEXT,
  metadata      JSONB,
  updated_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE installed_extensions (
  id            BIGSERIAL PRIMARY KEY,
  extension_id  TEXT REFERENCES marketplace_extensions(extension_id) ON DELETE SET NULL,
  version       TEXT,
  installed_by  UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
  installed_at  TIMESTAMP DEFAULT now(),
  source        TEXT,                      -- local|marketplace
  directory     TEXT
);

CREATE TABLE usage_counters (
  id           BIGSERIAL PRIMARY KEY,
  tenant_id    TEXT,
  user_id      TEXT,
  metric       TEXT NOT NULL,              -- "messages","tool_calls","errors"
  value        BIGINT NOT NULL,
  window_start TIMESTAMP NOT NULL,
  window_end   TIMESTAMP NOT NULL
);

CREATE TABLE rate_limits (
  key          TEXT PRIMARY KEY,           -- tenant:user or api_key
  limit_name   TEXT,                       -- "chat_per_min"
  window_sec   INT,
  max_count    INT,
  current_count INT,
  window_reset TIMESTAMP
);

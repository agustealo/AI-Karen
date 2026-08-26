-- AI KAREN production baseline migration
-- Consolidated pre-production history. Future production changes are forward-only.
-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.


-- ============================================================================
-- BASELINE SOURCE: 20260823010000_agui_chat_core.sql
-- ============================================================================

﻿-- Migrated from database/migrations/001_agui_chat_core.sql (preserving original lineage)
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

-- ============================================================================
-- BASELINE SOURCE: 20260823020000_persona_persistence.sql
-- ============================================================================

﻿-- Migrated from database/migrations/003_persona_persistence.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

CREATE TABLE IF NOT EXISTS custom_personas (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    default_tone VARCHAR(32) NOT NULL,
    default_verbosity VARCHAR(32) NOT NULL,
    default_language VARCHAR(32) NOT NULL,
    memory_weight VARCHAR(32) NOT NULL DEFAULT 'medium',
    context_window_size INTEGER NOT NULL DEFAULT 10,
    domain_knowledge TEXT NOT NULL DEFAULT '[]',
    specialized_instructions TEXT,
    use_emoji BOOLEAN NOT NULL DEFAULT FALSE,
    formality_level FLOAT NOT NULL DEFAULT 0.5,
    creativity_level FLOAT NOT NULL DEFAULT 0.5,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_personas_user_name
ON custom_personas (tenant_id, user_id, lower(name));

CREATE INDEX IF NOT EXISTS idx_custom_personas_user_lookup
ON custom_personas (tenant_id, user_id, is_active);

CREATE TABLE IF NOT EXISTS persona_memory_entries (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    conversation_id VARCHAR(255),
    persona_id VARCHAR(64),
    persona_name VARCHAR(100),
    tone_used VARCHAR(32),
    verbosity_used VARCHAR(32),
    content TEXT NOT NULL,
    memory_type VARCHAR(64) NOT NULL DEFAULT 'chat_interaction',
    importance_score FLOAT NOT NULL DEFAULT 0.5,
    embedding_id VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_persona_memory_entries_user_lookup
ON persona_memory_entries (tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_persona_memory_entries_persona_lookup
ON persona_memory_entries (tenant_id, persona_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_persona_preferences (
    tenant_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    active_persona_id VARCHAR(64),
    default_tone VARCHAR(32) NOT NULL DEFAULT 'friendly',
    default_verbosity VARCHAR(32) NOT NULL DEFAULT 'balanced',
    default_language VARCHAR(32) NOT NULL DEFAULT 'en-US',
    enable_style_adaptation BOOLEAN NOT NULL DEFAULT TRUE,
    adaptation_sensitivity FLOAT NOT NULL DEFAULT 0.7,
    enable_persona_memory_filtering BOOLEAN NOT NULL DEFAULT TRUE,
    cross_persona_memory_sharing BOOLEAN NOT NULL DEFAULT FALSE,
    show_persona_selector BOOLEAN NOT NULL DEFAULT TRUE,
    show_style_controls BOOLEAN NOT NULL DEFAULT TRUE,
    enable_quick_style_adjustments BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_persona_preferences_active_persona
ON user_persona_preferences (active_persona_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_user_persona_preferences_active_persona'
    ) THEN
        ALTER TABLE user_persona_preferences
        ADD CONSTRAINT fk_user_persona_preferences_active_persona
        FOREIGN KEY (active_persona_id)
        REFERENCES custom_personas (id)
        ON DELETE SET NULL;
    END IF;
END
$$;

-- ============================================================================
-- BASELINE SOURCE: 20260823030000_chat_runtime_control_plane.sql
-- ============================================================================

﻿-- Migrated from database/migrations/004_chat_runtime_control_plane.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration: Add Chat Runtime Control Plane Tables
-- Description: Adds tables for runtime state management, maintenance windows, notifications, dependency health, and audit events
-- Created: 2026-04-09

-- Create system_runtime_state table
CREATE TABLE IF NOT EXISTS system_runtime_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    current_mode VARCHAR(50) NOT NULL DEFAULT 'normal' CHECK (current_mode IN ('normal', 'degraded', 'maintenance', 'emergency_fallback')),
    normal_ready BOOLEAN NOT NULL DEFAULT FALSE,
    degraded_ready BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_reason TEXT,
    estimated_completion_time TIMESTAMP WITH TIME ZONE,
    last_transition_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_transition_reason TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create maintenance_windows table
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    message TEXT,
    reason TEXT,
    estimated_completion_time TIMESTAMP WITH TIME ZONE,
    notifications_supported BOOLEAN NOT NULL DEFAULT TRUE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    auto_end_policy VARCHAR(100) DEFAULT 'manual',
    created_by UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    updated_by UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create maintenance_notification_requests table
CREATE TABLE IF NOT EXISTS maintenance_notification_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    maintenance_window_id UUID NOT NULL REFERENCES maintenance_windows(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth_users(user_id) ON DELETE CASCADE,
    session_id VARCHAR(255),
    notification_channel VARCHAR(50) DEFAULT 'in_app',
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'pending', 'completed', 'cancelled')),
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    dispatched_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE
);

-- Create runtime_dependency_health table
CREATE TABLE IF NOT EXISTS runtime_dependency_health (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dependency_name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('healthy', 'unhealthy', 'unknown')),
    reason TEXT,
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    consecutive_successes INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create chat_runtime_events table
CREATE TABLE IF NOT EXISTS chat_runtime_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    mode VARCHAR(50) CHECK (mode IN ('normal', 'degraded', 'maintenance', 'emergency_fallback')),
    user_id UUID REFERENCES auth_users(user_id) ON DELETE SET NULL,
    session_id VARCHAR(255),
    conversation_id UUID,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_runtime_state_mode ON system_runtime_state(current_mode);
CREATE INDEX IF NOT EXISTS idx_runtime_state_updated ON system_runtime_state(updated_at);

CREATE INDEX IF NOT EXISTS idx_maintenance_enabled ON maintenance_windows(enabled);
CREATE INDEX IF NOT EXISTS idx_maintenance_started ON maintenance_windows(started_at);
CREATE INDEX IF NOT EXISTS idx_maintenance_created ON maintenance_windows(created_at);

CREATE INDEX IF NOT EXISTS idx_notification_maintenance ON maintenance_notification_requests(maintenance_window_id);
CREATE INDEX IF NOT EXISTS idx_notification_user ON maintenance_notification_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_session ON maintenance_notification_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_notification_status ON maintenance_notification_requests(status);

CREATE INDEX IF NOT EXISTS idx_dependency_name ON runtime_dependency_health(dependency_name);
CREATE INDEX IF NOT EXISTS idx_dependency_status ON runtime_dependency_health(status);
CREATE INDEX IF NOT EXISTS idx_dependency_checked ON runtime_dependency_health(checked_at);

CREATE INDEX IF NOT EXISTS idx_runtime_event_type ON chat_runtime_events(event_type);
CREATE INDEX IF NOT EXISTS idx_runtime_event_user ON chat_runtime_events(user_id);
CREATE INDEX IF NOT EXISTS idx_runtime_event_session ON chat_runtime_events(session_id);
CREATE INDEX IF NOT EXISTS idx_runtime_event_created ON chat_runtime_events(created_at);

-- Insert initial runtime state
INSERT INTO system_runtime_state (current_mode, normal_ready, degraded_ready, maintenance_enabled)
VALUES ('normal', true, true, false)
ON CONFLICT DO NOTHING;

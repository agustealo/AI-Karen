-- Migrated from database/migrations/003_persona_persistence.sql (preserving original lineage)
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

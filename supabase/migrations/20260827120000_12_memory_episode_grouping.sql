-- MEMORY-RUNTIME: group event-specific memory_episode snapshots into coherent
-- multi-turn episodes while preserving the existing one-row-per-event schema.

ALTER TABLE memory_episode
    ADD COLUMN IF NOT EXISTS episode_group_id UUID,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS boundary_reason VARCHAR(100),
    ADD COLUMN IF NOT EXISTS context_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE memory_episode
SET episode_group_id = COALESCE(episode_group_id, episode_id),
    started_at = COALESCE(started_at, created_at)
WHERE episode_group_id IS NULL OR started_at IS NULL;

ALTER TABLE memory_episode
    ALTER COLUMN episode_group_id SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_episode_group
    ON memory_episode(tenant_id, user_id, episode_group_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_memory_episode_session_group
    ON memory_episode(tenant_id, user_id, session_id, episode_group_id);

COMMENT ON COLUMN memory_episode.episode_group_id IS
    'Logical multi-event episode identity; individual rows remain provenance-preserving event snapshots.';

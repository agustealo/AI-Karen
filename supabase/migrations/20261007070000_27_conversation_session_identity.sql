-- Canonicalize durable conversation session identity.
-- The schema has always owned conversations.session_id, but older runtime code
-- duplicated session identity inside conversation_metadata.

UPDATE conversations
SET session_id = NULLIF(conversation_metadata ->> 'session_id', '')
WHERE session_id IS NULL
  AND NULLIF(conversation_metadata ->> 'session_id', '') IS NOT NULL;

UPDATE conversations
SET conversation_metadata = COALESCE(conversation_metadata, '{}'::jsonb) - 'session_id'
WHERE conversation_metadata ? 'session_id';

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user_session
    ON conversations (tenant_id, user_id, session_id)
    WHERE session_id IS NOT NULL;

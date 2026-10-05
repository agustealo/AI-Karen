-- PERSONALIZATION-AUTHORITY-1
-- Durable behavioral learning evidence. User facts/preferences/goals remain
-- canonical memory projections and are never mutated through this table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.personalization_behavior_pattern (
    pattern_id varchar(64) PRIMARY KEY,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    pattern_type varchar(100) NOT NULL,
    context_signature text NOT NULL,
    observation_count integer NOT NULL DEFAULT 1,
    confidence double precision NOT NULL DEFAULT 0.0,
    first_seen timestamp NOT NULL,
    last_seen timestamp NOT NULL,
    recurrence varchar(50) NOT NULL,
    stability varchar(50) NOT NULL,
    metadata_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT personalization_behavior_pattern_observation_count_nonnegative
        CHECK (observation_count >= 0),
    CONSTRAINT personalization_behavior_pattern_confidence_range
        CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personalization_behavior_pattern_identity
    ON public.personalization_behavior_pattern (
        tenant_id,
        user_id,
        pattern_type,
        context_signature
    );

CREATE INDEX IF NOT EXISTS idx_personalization_behavior_pattern_user
    ON public.personalization_behavior_pattern (
        tenant_id,
        user_id,
        last_seen DESC
    );

ALTER TABLE public.personalization_behavior_pattern ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personalization_behavior_pattern FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS personalization_behavior_pattern_tenant_isolation
    ON public.personalization_behavior_pattern;
CREATE POLICY personalization_behavior_pattern_tenant_isolation
    ON public.personalization_behavior_pattern
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.personalization_behavior_pattern IS
    'Derived recurring behavior evidence. User facts/preferences/goals remain owned by canonical memory.';

COMMIT;

-- PERSONALIZATION-BEHAVIOR-OBSERVATION-1
-- Deduplicated user-behavior observations backing durable recurrence learning.
-- Raw prompt content is intentionally not stored here.

BEGIN;

CREATE TABLE IF NOT EXISTS public.personalization_behavior_observation (
    observation_id varchar(128) NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    pattern_type varchar(100) NOT NULL,
    context_signature text NOT NULL,
    observed_at timestamp NOT NULL,
    metadata_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id, observation_id)
);

CREATE INDEX IF NOT EXISTS idx_personalization_behavior_observation_pattern
    ON public.personalization_behavior_observation (
        tenant_id,
        user_id,
        pattern_type,
        context_signature,
        observed_at DESC
    );

ALTER TABLE public.personalization_behavior_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personalization_behavior_observation FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS personalization_behavior_observation_tenant_isolation
    ON public.personalization_behavior_observation;
CREATE POLICY personalization_behavior_observation_tenant_isolation
    ON public.personalization_behavior_observation
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.personalization_behavior_observation IS
    'Deduplicated explicit user-behavior evidence. Raw chat text and provider/runtime outcome data are not stored here.';

COMMIT;

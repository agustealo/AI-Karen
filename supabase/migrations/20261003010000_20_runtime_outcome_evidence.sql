-- REWARD-SPINE-1
-- Durable, tenant-scoped runtime outcome evidence.
-- Runtime records facts; Intelligence derives reward/progress projections.
-- No reward score stored here and no policy/RBAC authority is granted by outcomes.

BEGIN;

CREATE TABLE IF NOT EXISTS public.outcome_records (
    outcome_id text PRIMARY KEY,
    trajectory_id text,
    decision_observation_id text,
    request_id text,
    correlation_id text,
    message_id text,
    conversation_id text,
    session_id text,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    source text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL,
    CONSTRAINT outcome_records_source_check
        CHECK (source IN ('runtime.execution', 'user.feedback'))
);

CREATE INDEX IF NOT EXISTS idx_outcome_records_tenant_recorded
    ON public.outcome_records (tenant_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcome_records_tenant_user_recorded
    ON public.outcome_records (tenant_id, user_id, recorded_at DESC)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outcome_records_tenant_trajectory
    ON public.outcome_records (tenant_id, trajectory_id, recorded_at ASC)
    WHERE trajectory_id IS NOT NULL;

ALTER TABLE public.outcome_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcome_records FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS outcome_records_tenant_scope ON public.outcome_records;
CREATE POLICY outcome_records_tenant_scope ON public.outcome_records
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.outcome_records IS
    'Append-only tenant-scoped execution and user-feedback evidence. User deletion cascades user-scoped evidence. Reward/progress is derived, never authoritative.';
COMMENT ON COLUMN public.outcome_records.payload IS
    'Original outcome evidence payload. Runtime facts and user feedback remain separate source records.';

COMMIT;

-- LEARNING-SPINE-1
-- Durable, tenant-scoped runtime learning lineage.
-- Runtime records facts only; Intelligence evaluates them later.
-- No learned policy gains execution authority from these tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.execution_trajectories (
    trajectory_id text PRIMARY KEY,
    request_id text,
    correlation_id text,
    conversation_id text,
    session_id text,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    execution_status text,
    policy_decision_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_execution_trajectories_tenant_started
    ON public.execution_trajectories (tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_trajectories_tenant_user_started
    ON public.execution_trajectories (tenant_id, user_id, started_at DESC)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_execution_trajectories_correlation
    ON public.execution_trajectories (tenant_id, correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.feature_snapshots (
    feature_snapshot_id text PRIMARY KEY,
    trajectory_id text NOT NULL
        REFERENCES public.execution_trajectories(trajectory_id) ON DELETE CASCADE,
    request_id text NOT NULL,
    correlation_id text NOT NULL,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    feature_version text NOT NULL,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_tenant_created
    ON public.feature_snapshots (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_trajectory
    ON public.feature_snapshots (tenant_id, trajectory_id, created_at ASC);

CREATE TABLE IF NOT EXISTS public.decision_observations (
    decision_observation_id text PRIMARY KEY,
    trajectory_id text NOT NULL
        REFERENCES public.execution_trajectories(trajectory_id) ON DELETE CASCADE,
    feature_snapshot_id text NOT NULL
        REFERENCES public.feature_snapshots(feature_snapshot_id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    decision_type text NOT NULL,
    behavior_policy_id text NOT NULL,
    behavior_policy_version text NOT NULL,
    chosen_action text NOT NULL,
    ope_eligible boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_observations_tenant_created
    ON public.decision_observations (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_observations_trajectory
    ON public.decision_observations (tenant_id, trajectory_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_decision_observations_type
    ON public.decision_observations (tenant_id, decision_type, created_at DESC);

ALTER TABLE public.execution_trajectories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_trajectories FORCE ROW LEVEL SECURITY;
ALTER TABLE public.feature_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feature_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE public.decision_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.decision_observations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS execution_trajectories_tenant_scope
    ON public.execution_trajectories;
CREATE POLICY execution_trajectories_tenant_scope
    ON public.execution_trajectories
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS feature_snapshots_tenant_scope
    ON public.feature_snapshots;
CREATE POLICY feature_snapshots_tenant_scope
    ON public.feature_snapshots
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS decision_observations_tenant_scope
    ON public.decision_observations;
CREATE POLICY decision_observations_tenant_scope
    ON public.decision_observations
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.execution_trajectories IS
    'Tenant-scoped runtime decision/execution lineage. Stores references and execution facts, not raw chat content.';
COMMENT ON TABLE public.feature_snapshots IS
    'Immutable decision-time features used for supervised and off-policy learning.';
COMMENT ON TABLE public.decision_observations IS
    'Immutable behavior-policy observations linking legal actions and chosen actions to outcomes.';

COMMIT;

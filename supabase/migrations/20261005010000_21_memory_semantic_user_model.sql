-- MEMORY-SEMANTIC-FORMATION-1
-- Durable projections for goals and prospective user-memory state.
-- NeuroVault/memory_event remains the mutation authority. These tables are
-- rebuildable user-model views with tenant/user isolation and cascade erasure.

BEGIN;

CREATE TABLE IF NOT EXISTS public.memory_user_goal (
    goal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL UNIQUE
        REFERENCES public.memory_event(event_id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    description text NOT NULL,
    goal_type varchar(50) NOT NULL DEFAULT 'explicit',
    lifecycle_state varchar(50) NOT NULL DEFAULT 'active',
    confidence double precision NOT NULL DEFAULT 1.0,
    source_type varchar(100) NOT NULL,
    source_ref varchar(255),
    target_text text,
    target_at timestamp,
    valid_from timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to timestamp,
    supersedes uuid,
    metadata_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_user_goal_tenant_user_state
    ON public.memory_user_goal (tenant_id, user_id, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_memory_user_goal_validity
    ON public.memory_user_goal (tenant_id, user_id, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS public.memory_prospective_item (
    prospective_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL UNIQUE
        REFERENCES public.memory_event(event_id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    event_type varchar(100) NOT NULL,
    description text NOT NULL,
    temporal_text text,
    target_at timestamp,
    lifecycle_state varchar(50) NOT NULL DEFAULT 'dormant',
    confidence double precision NOT NULL DEFAULT 1.0,
    source_type varchar(100) NOT NULL,
    source_ref varchar(255),
    valid_from timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to timestamp,
    metadata_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_prospective_tenant_user_state
    ON public.memory_prospective_item (tenant_id, user_id, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_memory_prospective_target
    ON public.memory_prospective_item (tenant_id, user_id, target_at);

ALTER TABLE public.memory_user_goal ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_user_goal FORCE ROW LEVEL SECURITY;
ALTER TABLE public.memory_prospective_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_prospective_item FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_user_goal_tenant_isolation
    ON public.memory_user_goal;
CREATE POLICY memory_user_goal_tenant_isolation ON public.memory_user_goal
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

DROP POLICY IF EXISTS memory_prospective_item_tenant_isolation
    ON public.memory_prospective_item;
CREATE POLICY memory_prospective_item_tenant_isolation
    ON public.memory_prospective_item
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.memory_user_goal IS
    'Derived tenant/user-scoped goal state. Canonical source is the governed memory_event referenced by event_id.';
COMMENT ON TABLE public.memory_prospective_item IS
    'Derived time/context-relevant user memory. Canonical source is the governed memory_event referenced by event_id.';

COMMIT;

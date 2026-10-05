-- MEMORY-CONTINUITY-1
-- Domain-neutral durable open loops for unfinished work and commitments.
-- The source memory_event remains canonical truth. This table is a rebuildable
-- user-state projection and never authorizes execution.

BEGIN;

CREATE TABLE IF NOT EXISTS public.memory_open_loop (
    open_loop_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL UNIQUE
        REFERENCES public.memory_event(event_id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    loop_type varchar(50) NOT NULL DEFAULT 'unfinished_work',
    description text NOT NULL,
    domain varchar(100),
    lifecycle_state varchar(50) NOT NULL DEFAULT 'open',
    confidence double precision NOT NULL DEFAULT 1.0,
    source_type varchar(100) NOT NULL,
    source_ref varchar(255),
    target_text text,
    target_at timestamp,
    valid_from timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_to timestamp,
    metadata_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_open_loop_tenant_user_state
    ON public.memory_open_loop (tenant_id, user_id, lifecycle_state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_open_loop_target
    ON public.memory_open_loop (tenant_id, user_id, target_at);

ALTER TABLE public.memory_open_loop ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_open_loop FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_open_loop_tenant_isolation
    ON public.memory_open_loop;
CREATE POLICY memory_open_loop_tenant_isolation ON public.memory_open_loop
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.memory_open_loop IS
    'Derived unfinished-work/commitment state. Canonical evidence is the governed memory_event referenced by event_id.';

COMMIT;

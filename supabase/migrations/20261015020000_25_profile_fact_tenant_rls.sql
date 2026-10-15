-- MI-04: Close the profile projection tenant isolation gap.
-- The canonical memory_event RLS is not a substitute for RLS on profile_fact,
-- which is queried and updated independently by maintenance and projection.

BEGIN;

ALTER TABLE public.profile_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_fact FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profile_fact_tenant_isolation ON public.profile_fact;

CREATE POLICY profile_fact_tenant_isolation ON public.profile_fact
    FOR ALL
    USING (
        tenant_id = NULLIF(
            current_setting('app.current_tenant_id', true), ''
        )::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(
            current_setting('app.current_tenant_id', true), ''
        )::uuid
    );

COMMENT ON TABLE public.profile_fact IS
    'Tenant-isolated rebuildable profile view derived from governed memory_event. RLS and canonical consented event provenance are required.';

COMMIT;

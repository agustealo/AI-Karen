-- Govern shared artifact downloads without leaking jobs across tenants.
-- Existing jobs are intentionally unowned until an administrator reconciles them.
ALTER TABLE public.model_download_jobs
    ADD COLUMN IF NOT EXISTS tenant_id text;

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_tenant_owner_created
    ON public.model_download_jobs (tenant_id, requested_by, created_at DESC)
    WHERE tenant_id IS NOT NULL;

-- No inferred ownership for legacy rows: fail closed in consumer projections.
COMMENT ON COLUMN public.model_download_jobs.tenant_id IS
    'Verified tenant identity of the original download requester; null legacy rows remain admin-only.';

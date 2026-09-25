-- Preserve original model-publication receipt identity across rotating recovery leases.
-- PostgreSQL remains the sole lifecycle authority. The source token is evidence
-- identity only and never grants execution authority.

ALTER TABLE public.model_download_jobs
    ADD COLUMN IF NOT EXISTS publication_source_lease_token uuid;

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_publication_recovery
    ON public.model_download_jobs (available_at, updated_at)
    WHERE status = 'promoting'
      AND publication_source_lease_token IS NOT NULL;

COMMENT ON COLUMN public.model_download_jobs.publication_source_lease_token IS
    'Original publication lease token used only to locate crash-recovery evidence; recovery execution authority uses lease_token separately.';

-- Keep model-publication residue cleanup restart-safe after durable completion.
-- PostgreSQL remains the sole lifecycle authority. The source lease token is
-- evidence identity only and stays present until committed filesystem residue
-- has been removed and cleanup is acknowledged.

UPDATE public.model_download_jobs
SET publication_source_lease_token = lease_token
WHERE status = 'promoting'
  AND publication_source_lease_token IS NULL
  AND lease_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_publication_cleanup
    ON public.model_download_jobs (completed_at, updated_at)
    WHERE status = 'completed'
      AND publication_source_lease_token IS NOT NULL;

COMMENT ON COLUMN public.model_download_jobs.publication_source_lease_token IS
    'Original publication lease token used only as crash-recovery and terminal-cleanup evidence identity; execution authority uses lease_token separately, and this token is cleared only after committed publication residue cleanup is acknowledged.';

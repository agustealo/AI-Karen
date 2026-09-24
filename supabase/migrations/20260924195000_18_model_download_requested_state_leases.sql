-- Keep durable pause requests inside installation-wide active-lease accounting.
-- Running cancel requests retain status='running' with cancel_requested=true,
-- so they are already covered by the existing active status set.

DROP INDEX IF EXISTS public.idx_model_download_jobs_active_lease;

CREATE INDEX idx_model_download_jobs_active_lease
    ON public.model_download_jobs (lease_expires_at)
    WHERE status IN ('running', 'promoting', 'pause_requested')
      AND lease_token IS NOT NULL;

COMMENT ON INDEX public.idx_model_download_jobs_active_lease IS
    'Supports installation-wide concurrency accounting while running, promoting, or draining an active pause request.';

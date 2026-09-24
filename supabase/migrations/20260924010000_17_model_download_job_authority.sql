-- Durable installation-wide model download lifecycle authority.
-- PostgreSQL is the sole job-state and global-concurrency authority. Model
-- artifacts remain on the shared installation filesystem and are promoted only
-- by a valid lease holder.

CREATE OR REPLACE FUNCTION public.set_model_download_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION public.set_model_download_updated_at() FROM PUBLIC;

CREATE TABLE IF NOT EXISTS public.model_download_runtime_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton = true),
    max_concurrent_downloads integer NOT NULL CHECK (max_concurrent_downloads BETWEEN 1 AND 8),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_model_download_runtime_settings_updated_at ON public.model_download_runtime_settings;
CREATE TRIGGER trg_model_download_runtime_settings_updated_at
BEFORE UPDATE ON public.model_download_runtime_settings
FOR EACH ROW EXECUTE FUNCTION public.set_model_download_updated_at();

CREATE TABLE IF NOT EXISTS public.model_download_jobs (
    job_id text PRIMARY KEY,
    model_id text NOT NULL,
    revision text,
    channel_id text NOT NULL,
    storage_key text,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'promoting', 'paused', 'pause_requested', 'completed', 'failed', 'cancelled')),
    progress double precision NOT NULL DEFAULT 0
        CHECK (progress >= 0 AND progress <= 1),
    message text NOT NULL DEFAULT 'Queued',
    error text,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    requested_by text,
    trust_remote_code boolean NOT NULL DEFAULT false,
    license_accepted boolean NOT NULL DEFAULT false,
    include_patterns jsonb,
    exclude_patterns jsonb,
    pin boolean NOT NULL DEFAULT false,
    force_redownload boolean NOT NULL DEFAULT false,
    pause_requested boolean NOT NULL DEFAULT false,
    cancel_requested boolean NOT NULL DEFAULT false,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    detected_runtime text,
    detected_modality text,
    install_path text,
    available_at timestamptz NOT NULL DEFAULT now(),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    dead_lettered_at timestamptz,
    legacy_imported_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_claim
    ON public.model_download_jobs (status, available_at, created_at)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_active_lease
    ON public.model_download_jobs (lease_expires_at)
    WHERE status IN ('running', 'promoting') AND lease_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_model_download_jobs_updated
    ON public.model_download_jobs (updated_at DESC);

DROP TRIGGER IF EXISTS trg_model_download_jobs_updated_at ON public.model_download_jobs;
CREATE TRIGGER trg_model_download_jobs_updated_at
BEFORE UPDATE ON public.model_download_jobs
FOR EACH ROW EXECUTE FUNCTION public.set_model_download_updated_at();

ALTER TABLE public.model_download_runtime_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_download_jobs ENABLE ROW LEVEL SECURITY;

-- Supabase installations define anon/authenticated/service_role, while the
-- canonical local-first and first-boot paths may run against plain PostgreSQL.
-- PostgreSQL grants no table privileges to PUBLIC by default, so missing
-- Supabase roles must not make this otherwise portable migration fail.
DO $acl$
BEGIN
    IF to_regrole('anon') IS NOT NULL THEN
        EXECUTE 'REVOKE ALL ON TABLE public.model_download_runtime_settings FROM anon';
        EXECUTE 'REVOKE ALL ON TABLE public.model_download_jobs FROM anon';
    END IF;
    IF to_regrole('authenticated') IS NOT NULL THEN
        EXECUTE 'REVOKE ALL ON TABLE public.model_download_runtime_settings FROM authenticated';
        EXECUTE 'REVOKE ALL ON TABLE public.model_download_jobs FROM authenticated';
    END IF;
    IF to_regrole('service_role') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE public.model_download_runtime_settings TO service_role';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.model_download_jobs TO service_role';
    END IF;
END
$acl$;

COMMENT ON FUNCTION public.set_model_download_updated_at() IS
    'Keeps durable model-download authority timestamps current without depending on optional Supabase helpers.';

COMMENT ON TABLE public.model_download_runtime_settings IS
    'Installation-wide durable runtime settings for model-download workers. The singleton row is initialized by the canonical runtime and updated by the model-download policy authority.';

COMMENT ON TABLE public.model_download_jobs IS
    'Installation-wide durable lifecycle authority for model download jobs. Claims and final promotion are lease-fenced and concurrency-limited by the PostgreSQL runtime-settings row.';

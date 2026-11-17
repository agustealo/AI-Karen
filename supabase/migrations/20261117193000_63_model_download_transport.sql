-- KMOD-02: persist the chosen transfer method on the existing durable model job.
-- One worker queue, one lease, one validated publication pipeline.
-- Existing jobs remain Hugging Face Hub downloads with no state migration.

ALTER TABLE public.model_download_jobs
    ADD COLUMN IF NOT EXISTS download_method text NOT NULL DEFAULT 'hf_hub';

DO $block$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'model_download_jobs_download_method_check'
          AND conrelid = 'public.model_download_jobs'::regclass
    ) THEN
        ALTER TABLE public.model_download_jobs
            ADD CONSTRAINT model_download_jobs_download_method_check
            CHECK (download_method IN ('hf_hub', 'direct_https'));
    END IF;
END
$block$;

COMMENT ON COLUMN public.model_download_jobs.download_method IS
    'Host-chosen verified transfer backend only. Both methods use the same license, tenant scope, audited worker lease and atomic publication.';

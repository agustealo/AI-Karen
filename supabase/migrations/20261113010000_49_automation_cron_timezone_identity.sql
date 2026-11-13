-- KCON-490: preserve civil-time recurrence independently of UTC claim instants.
-- Existing cron schedules were evaluated in UTC and keep that behavior.
-- New named-zone daily schedules retain their IANA identifier and local wall time.
BEGIN;

ALTER TABLE public.automation_cron_jobs
    ADD COLUMN IF NOT EXISTS timezone_id text NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS local_time time without time zone;

ALTER TABLE public.automation_cron_jobs
    DROP CONSTRAINT IF EXISTS automation_cron_timezone_id_format;
ALTER TABLE public.automation_cron_jobs
    ADD CONSTRAINT automation_cron_timezone_id_format
    CHECK (
        length(timezone_id) BETWEEN 1 AND 128
        AND timezone_id = btrim(timezone_id)
    );

COMMENT ON COLUMN public.automation_cron_jobs.timezone_id IS
    'Canonical IANA zone for interpreting recurring local schedule (UTC for legacy definitions). Not a user location.';
COMMENT ON COLUMN public.automation_cron_jobs.local_time IS
    'Daily wall-clock time for locally recurring schedules; NULL for general cron definitions. Never a fixed UTC offset.';
COMMENT ON COLUMN public.automation_cron_jobs.next_run_at IS
    'Absolute UTC execution instant derived from cron expression and timezone_id; recompute after each claim with zone rules.';

COMMIT;

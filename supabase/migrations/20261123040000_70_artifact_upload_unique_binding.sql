-- KFILE-UPLOAD-01G: one durable upload-session owner per artifact.
-- A duplicate existing binding is a migration-blocking integrity defect:
-- never silently discard or rewrite an existing upload receipt.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS artifact_upload_sessions_artifact_unique_idx
    ON public.artifact_upload_sessions (artifact_id)
    WHERE artifact_id IS NOT NULL;

COMMIT;

-- KFILE-UPLOAD-01D: align the existing upload ledger tenant type with
-- canonical files. This forward-only migration is safe for installed schema.
BEGIN;
ALTER TABLE public.artifact_upload_sessions
    ALTER COLUMN tenant_id TYPE UUID USING tenant_id::uuid;
COMMIT;

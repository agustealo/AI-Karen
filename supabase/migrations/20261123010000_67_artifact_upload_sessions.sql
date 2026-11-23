-- KFILE-UPLOAD-01C: canonical, durable upload-session ledger.
-- No API exposure or upload activation in this migration.
-- Sessions are private to trusted runtime/service-role access; RLS has no
-- permissive client policies. Runtime must enforce tenant and owner identity.
BEGIN;

CREATE TABLE IF NOT EXISTS public.artifact_upload_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    owner_user_id UUID NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    destination_id TEXT NOT NULL,
    recipe TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    expected_bytes BIGINT NOT NULL CHECK (expected_bytes >= 0),
    received_bytes BIGINT NOT NULL DEFAULT 0 CHECK (received_bytes >= 0),
    expected_sha256 TEXT CHECK (expected_sha256 IS NULL OR expected_sha256 ~ '^[0-9a-f]{64}$'),
    artifact_id TEXT REFERENCES public.files(file_id) ON DELETE SET NULL,
    state TEXT NOT NULL DEFAULT 'created' CHECK (
        state IN ('created', 'receiving', 'staged', 'committing',
                  'committed', 'failed', 'cancelled', 'reconcile_required')
    ),
    storage_key TEXT,
    lease_owner TEXT,
    lease_expires_at TIMESTAMP,
    failure_code TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    expires_at TIMESTAMP NOT NULL,
    CHECK (received_bytes <= expected_bytes),
    CHECK ((state <> 'committed') OR artifact_id IS NOT NULL),
    UNIQUE (tenant_id, owner_user_id, idempotency_key_hash)
);

CREATE INDEX IF NOT EXISTS artifact_upload_sessions_reconcile_idx
    ON public.artifact_upload_sessions (state, updated_at)
    WHERE state IN ('committing', 'reconcile_required');

CREATE INDEX IF NOT EXISTS artifact_upload_sessions_owner_idx
    ON public.artifact_upload_sessions (tenant_id, owner_user_id, created_at DESC);

ALTER TABLE public.artifact_upload_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_upload_sessions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.artifact_upload_sessions FROM PUBLIC;
-- Do not add an anonymous/authenticated policy. Trusted server runtime must
-- use its explicitly provisioned DB role and enforce actor-scoped mutations.
COMMIT;

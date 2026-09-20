-- CONSUMER-IDENTITY-2B
-- Durable privacy request lifecycle for authenticated self-service.
-- Runtime code must never create this table or fall back to process memory.

BEGIN;

CREATE TABLE IF NOT EXISTS public.privacy_requests (
    request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    request_type varchar(32) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending',
    data_types jsonb NOT NULL DEFAULT '["all"]'::jsonb,
    export_format varchar(16),
    erasure_type varchar(32),
    verification_token_hash char(64) NOT NULL,
    verification_used_at timestamp without time zone,
    result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    correlation_id text,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now(),
    completed_at timestamp without time zone,
    CONSTRAINT privacy_requests_type_check
        CHECK (request_type IN ('export', 'erasure')),
    CONSTRAINT privacy_requests_status_check
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')),
    CONSTRAINT privacy_requests_export_format_check
        CHECK (export_format IS NULL OR export_format IN ('json', 'csv', 'xml')),
    CONSTRAINT privacy_requests_erasure_type_check
        CHECK (erasure_type IS NULL OR erasure_type IN ('soft_delete', 'hard_delete', 'anonymize'))
);

CREATE INDEX IF NOT EXISTS idx_privacy_requests_tenant_user_created
    ON public.privacy_requests (tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_privacy_requests_status_created
    ON public.privacy_requests (status, created_at);

ALTER TABLE public.privacy_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.privacy_requests FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_requests_self_scope ON public.privacy_requests;
CREATE POLICY privacy_requests_self_scope ON public.privacy_requests
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

COMMENT ON TABLE public.privacy_requests IS
    'Durable self-service privacy request state. Verification tokens are stored only as SHA-256 hashes.';
COMMENT ON COLUMN public.privacy_requests.verification_token_hash IS
    'SHA-256 hash of the one-time confirmation token. Raw tokens must never be persisted.';

COMMIT;

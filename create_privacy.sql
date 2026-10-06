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
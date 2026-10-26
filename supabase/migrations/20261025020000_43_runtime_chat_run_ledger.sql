-- CK-07A: durable AG-UI chat run admission and fenced terminal authority.
-- Transcript storage remains in the canonical conversation repository.
-- This table contains only execution identity, leases, timestamps and outcomes.
-- Apply before enabling KARI_ENABLE_AG_UI_DURABLE_RUNS; no runtime DDL.

BEGIN;

CREATE TABLE public.runtime_chat_runs (
    execution_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    conversation_id UUID NOT NULL,
    transport_run_id VARCHAR(100) NOT NULL,
    request_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    terminal_error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_runtime_chat_run_status CHECK (
        status IN ('running', 'cancelling', 'completed', 'failed', 'cancelled', 'orphaned')
    ),
    CONSTRAINT ck_runtime_chat_run_terminal CHECK (
        (
            status IN ('running', 'cancelling')
            AND terminal_at IS NULL
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL
        ) OR (
            status IN ('completed', 'failed', 'cancelled', 'orphaned')
            AND terminal_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_runtime_chat_transport_id CHECK (
        LENGTH(transport_run_id) BETWEEN 1 AND 100
        AND transport_run_id ~ '^[A-Za-z0-9_-]+$'
    ),
    CONSTRAINT uq_runtime_chat_run_scoped_transport UNIQUE (
        tenant_id, user_id, conversation_id, transport_run_id
    )
);

CREATE INDEX idx_runtime_chat_run_owner_status
    ON public.runtime_chat_runs (tenant_id, user_id, conversation_id, status, created_at DESC);
CREATE INDEX idx_runtime_chat_run_active_expiry
    ON public.runtime_chat_runs (lease_expires_at)
    WHERE status IN ('running', 'cancelling');
CREATE INDEX idx_runtime_chat_run_correlation
    ON public.runtime_chat_runs (tenant_id, correlation_id);

ALTER TABLE public.runtime_chat_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_chat_runs FORCE ROW LEVEL SECURITY;

CREATE POLICY runtime_chat_run_scoped_execution
    ON public.runtime_chat_runs
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

COMMENT ON TABLE public.runtime_chat_runs IS
    'Runtime-owned, principal-scoped in-flight AG-UI execution and lease evidence; no transcript, tools, prompts or provider payloads.';
COMMENT ON COLUMN public.runtime_chat_runs.transport_run_id IS
    'Untrusted SDK correlation value scoped by tenant, owner and conversation; never used as authorization.';
COMMENT ON COLUMN public.runtime_chat_runs.lease_token IS
    'Server-issued execution fencing token; only its owning worker can renew or finalize.';

COMMIT;

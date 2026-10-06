-- HUMAN-GATE-1
-- Durable, tenant-scoped pre-execution approval authority.
-- Runtime may only execute a gated request after consuming an approved,
-- request-bound receipt. UI/API routes never grant execution directly.

BEGIN;

CREATE TABLE IF NOT EXISTS public.runtime_approval_requests (
    approval_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    conversation_id uuid,
    request_fingerprint text NOT NULL,
    policy_decision_id text,
    intent text NOT NULL,
    risk_level text NOT NULL,
    reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    request_payload jsonb NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending',
    decision_reason text,
    decided_by uuid REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    decided_at timestamptz,
    consumed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT runtime_approval_status_check
        CHECK (status IN ('pending', 'approved', 'rejected', 'consumed', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_approvals_tenant_status_created
    ON public.runtime_approval_requests (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_approvals_user_status
    ON public.runtime_approval_requests (tenant_id, user_id, status);
CREATE INDEX IF NOT EXISTS idx_runtime_approvals_expires
    ON public.runtime_approval_requests (expires_at)
    WHERE status IN ('pending', 'approved');

ALTER TABLE public.runtime_approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.runtime_approval_requests FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS runtime_approval_tenant_scope
    ON public.runtime_approval_requests;
CREATE POLICY runtime_approval_tenant_scope
    ON public.runtime_approval_requests
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    );

COMMENT ON TABLE public.runtime_approval_requests IS
    'Durable pre-execution human approval receipts owned by Runtime. Receipts are tenant/user/request scoped and one-shot.';

COMMIT;

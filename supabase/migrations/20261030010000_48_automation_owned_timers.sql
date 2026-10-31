-- Canonical durable timer ledger. A timer is a persisted countdown deadline;
-- it is NOT a notification or evidence of reminder delivery.
BEGIN;

CREATE TABLE public.automation_timers (
    timer_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    idempotency_key uuid NOT NULL,
    duration_seconds integer NOT NULL CHECK (duration_seconds BETWEEN 1 AND 86400),
    title varchar(240) NOT NULL DEFAULT 'Timer',
    status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'cancelled')),
    started_at timestamptz NOT NULL DEFAULT now(),
    deadline_at timestamptz NOT NULL,
    cancelled_at timestamptz,
    correlation_id varchar(128) NOT NULL CHECK (length(btrim(correlation_id)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT automation_timer_deadline_after_start CHECK (deadline_at > started_at),
    CONSTRAINT automation_timer_cancel_state CHECK (
        (status = 'cancelled' AND cancelled_at IS NOT NULL)
        OR (status = 'active' AND cancelled_at IS NULL)
    ),
    CONSTRAINT uq_automation_timer_idempotency
        UNIQUE (tenant_id, owner_id, idempotency_key)
);

CREATE INDEX idx_automation_timers_owner_deadline
    ON public.automation_timers (tenant_id, owner_id, deadline_at DESC);

ALTER TABLE public.automation_timers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_timers FORCE ROW LEVEL SECURITY;

CREATE POLICY automation_timers_owner_scope ON public.automation_timers
    USING (
        tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid
        AND owner_id = nullif(current_setting('app.current_user_id', true), '')::uuid
    );

COMMENT ON TABLE public.automation_timers IS
    'Tenant/user owned countdown deadlines; no notification scheduling or delivery implied.';
COMMIT;

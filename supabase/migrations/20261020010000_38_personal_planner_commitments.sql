-- Personal commitments are user-owned plans, not automation task definitions.
BEGIN;
CREATE TABLE public.personal_planner_commitments (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    project_id uuid,
    title varchar(240) NOT NULL CHECK (length(btrim(title)) > 0),
    description text NOT NULL DEFAULT '',
    status varchar(32) NOT NULL DEFAULT 'todo'
        CHECK (status IN ('todo', 'in_progress', 'completed', 'cancelled')),
    priority varchar(16) NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high')),
    due_at timestamptz,
    timezone varchar(128) NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_personal_planner_commitment_scope UNIQUE (id, tenant_id, owner_id)
);
CREATE INDEX idx_personal_planner_owner_due
    ON public.personal_planner_commitments (tenant_id, owner_id, due_at);
CREATE TABLE public.personal_planner_mutation_receipts (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE RESTRICT,
    idempotency_key uuid NOT NULL,
    request_fingerprint varchar(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}
    revision integer NOT NULL CHECK (revision >= 1),
    correlation_id varchar(128) NOT NULL,
    persisted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_id, idempotency_key),
    CONSTRAINT fk_personal_planner_receipt_owner
        FOREIGN KEY (commitment_id, tenant_id, owner_id)
        REFERENCES public.personal_planner_commitments (id, tenant_id, owner_id)
        ON DELETE CASCADE
);
ALTER TABLE public.personal_planner_commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_planner_commitments FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_planner_commitments_tenant ON public.personal_planner_commitments
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
ALTER TABLE public.personal_planner_mutation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_planner_mutation_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_planner_receipts_tenant ON public.personal_planner_mutation_receipts
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
COMMIT;
),
    commitment_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    correlation_id varchar(128) NOT NULL,
    persisted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_id, idempotency_key),
    CONSTRAINT fk_personal_planner_receipt_owner
        FOREIGN KEY (commitment_id, tenant_id, owner_id)
        REFERENCES public.personal_planner_commitments (id, tenant_id, owner_id)
        ON DELETE CASCADE
);
ALTER TABLE public.personal_planner_commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_planner_commitments FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_planner_commitments_tenant ON public.personal_planner_commitments
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
ALTER TABLE public.personal_planner_mutation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.personal_planner_mutation_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY personal_planner_receipts_tenant ON public.personal_planner_mutation_receipts
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant_id', true), '')::uuid);
COMMIT;

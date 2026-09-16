-- AUTH-TENANT-AUTHORITY-1
-- Restore the migration-owned tenant table required by canonical AuthService.
-- Runtime startup must not synthesize tenants or default users.

BEGIN;

CREATE TABLE IF NOT EXISTS public.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    slug varchar(100) NOT NULL UNIQUE,
    subscription_tier varchar(50) NOT NULL DEFAULT 'basic',
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    updated_at timestamp without time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_slug
    ON public.tenants (slug);

CREATE INDEX IF NOT EXISTS idx_tenant_active
    ON public.tenants (is_active);

-- Existing pre-baseline installations may contain historical tenant UUIDs that
-- predate the canonical tenants table. NOT VALID preserves those rows while
-- enforcing the foreign key for all new/updated auth users. A later data repair
-- may validate the constraint after legacy tenant identities are reconciled.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.auth_users'::regclass
          AND confrelid = 'public.tenants'::regclass
          AND contype = 'f'
    ) THEN
        ALTER TABLE public.auth_users
            ADD CONSTRAINT fk_auth_users_tenant
            FOREIGN KEY (tenant_id)
            REFERENCES public.tenants (id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;
END
$$;

COMMENT ON TABLE public.tenants IS
    'Canonical durable tenant authority used by authentication and tenant isolation.';

COMMIT;

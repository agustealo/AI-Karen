-- KOC-05: prevent implicit destruction of personal consent and deletion evidence.
-- Ordinary direct connection deletion cannot remove retained personal evidence.
-- Tenant/user account erasure remains a separately governed cascading operation.
-- NO ACTION is deferred to permit a single statement to remove dependent
-- tenant/user data without transient violations. No provider deletion is claimed.
BEGIN;

-- Keep the owner record when a single connection is removed accidentally.
ALTER TABLE public.channel_connection_owners
    DROP CONSTRAINT channel_owner_connection,
    ADD CONSTRAINT channel_owner_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.channel_personal_pairing_consents
    DROP CONSTRAINT channel_pairing_consent_connection,
    ADD CONSTRAINT channel_pairing_consent_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.channel_personal_pairing_consents
    ALTER CONSTRAINT channel_pairing_consent_owner
        DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.channel_personal_pairing_state
    DROP CONSTRAINT channel_personal_pairing_connection,
    ADD CONSTRAINT channel_personal_pairing_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

-- Migration 35 declared its connection and owner FKs without names. Resolve
-- only the exact current FK by referenced table and refuse ambiguous schemas.
DO $koc_05$
DECLARE
    current_fk name;
    matches integer;
BEGIN
    SELECT count(*), min(conname) INTO matches, current_fk
    FROM pg_constraint
    WHERE contype = 'f'
      AND conrelid = 'public.channel_personal_credential_deletions'::regclass
      AND confrelid = 'public.channel_connections'::regclass;
    IF matches <> 1 THEN
        RAISE EXCEPTION 'KOC-05 deletion connection constraint drift';
    END IF;
    EXECUTE format(
        'ALTER TABLE public.channel_personal_credential_deletions DROP CONSTRAINT %I',
        current_fk
    );
    SELECT count(*), min(conname) INTO matches, current_fk
    FROM pg_constraint
    WHERE contype = 'f'
      AND conrelid = 'public.channel_personal_credential_deletions'::regclass
      AND confrelid = 'public.channel_connection_owners'::regclass;
    IF matches <> 1 THEN
        RAISE EXCEPTION 'KOC-05 deletion owner constraint drift';
    END IF;
    EXECUTE format(
        'ALTER TABLE public.channel_personal_credential_deletions DROP CONSTRAINT %I',
        current_fk
    );
END
$koc_05$;

ALTER TABLE public.channel_personal_credential_deletions
    ADD CONSTRAINT channel_personal_deletion_connection
        FOREIGN KEY (tenant_id, connection_id)
        REFERENCES public.channel_connections(tenant_id, connection_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT channel_personal_deletion_owner
        FOREIGN KEY (tenant_id, connection_id, user_id)
        REFERENCES public.channel_connection_owners(tenant_id, connection_id, user_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT channel_personal_deletion_tenant
        FOREIGN KEY (tenant_id) REFERENCES public.tenants(id)
        ON DELETE CASCADE,
    ADD CONSTRAINT channel_personal_deletion_user
        FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.auth_users(tenant_id, user_id)
        ON DELETE CASCADE;

-- Pairing state and credential-deletion requests previously depended only on
-- connection cascades for tenant cleanup. Keep explicit tenant-level erasure.
ALTER TABLE public.channel_personal_pairing_state
    ADD CONSTRAINT channel_personal_pairing_tenant
        FOREIGN KEY (tenant_id) REFERENCES public.tenants(id)
        ON DELETE CASCADE;

-- The canonical runtime only INSERTs, reads and updates these records.
-- Do not let a tenant-scoped SQL role directly DELETE audit/consent rows.
-- Referential cascading actions are internal FK operations, not client DELETE.
DROP POLICY channel_connection_owner_tenant_scope
    ON public.channel_connection_owners;
DROP POLICY channel_pairing_consent_tenant_scope
    ON public.channel_personal_pairing_consents;
DROP POLICY channel_personal_pairing_tenant_scope
    ON public.channel_personal_pairing_state;
DROP POLICY channel_personal_deletions_tenant_scope
    ON public.channel_personal_credential_deletions;

DO $koc_policy$
DECLARE
    scoped_table text;
    policy_prefix text;
BEGIN
    FOR scoped_table, policy_prefix IN
        SELECT * FROM (VALUES
            ('channel_connection_owners', 'channel_owner'),
            ('channel_personal_pairing_consents', 'channel_consent'),
            ('channel_personal_pairing_state', 'channel_pairing'),
            ('channel_personal_credential_deletions', 'channel_deletion')
        ) AS p(tbl, pref)
    LOOP
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR SELECT USING '
            || '(tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid)',
            policy_prefix || '_tenant_select', scoped_table
        );
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR INSERT WITH CHECK '
            || '(tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid)',
            policy_prefix || '_tenant_insert', scoped_table
        );
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR UPDATE USING '
            || '(tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid)'
            || ' WITH CHECK '
            || '(tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')::uuid)',
            policy_prefix || '_tenant_update', scoped_table
        );
    END LOOP;
END
$koc_policy$;

COMMENT ON CONSTRAINT channel_owner_connection
    ON public.channel_connection_owners IS
    'KOC-05: connection deletion cannot implicitly discard operator ownership; tenant/user erasure remains governed separately.';
COMMENT ON CONSTRAINT channel_personal_deletion_connection
    ON public.channel_personal_credential_deletions IS
    'KOC-05: deletion intent and provider claims survive attempted direct connection removal; not proof of erasure.';

COMMIT;

-- KCM-01D2A: scoped training-source ancestry and monotonic deletion epoch.
-- Derived governance metadata only. NeuroVault remains the memory authority.
-- No example is authorized for training by this migration.
BEGIN;

-- Privileged mutation functions are not exposed through the public Data API.
CREATE SCHEMA IF NOT EXISTS kcm_internal;
REVOKE ALL ON SCHEMA kcm_internal FROM PUBLIC;

CREATE TABLE public.kcm_training_scope_state (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    deletion_epoch bigint NOT NULL DEFAULT 0 CHECK (deletion_epoch >= 0),
    training_authorized boolean NOT NULL DEFAULT false CHECK (training_authorized = false),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE public.kcm_dataset_source_lineage (
    lineage_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    dataset_version integer NOT NULL CHECK (dataset_version > 0),
    assessment_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    source_revision char(64) NOT NULL
        CHECK (source_revision ~ '^[0-9a-f]{64}$'),
    manifest_sha256 char(64) NOT NULL
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    split text NOT NULL CHECK (split IN ('train', 'dev', 'test')),
    leakage_group_id text NOT NULL CHECK (length(trim(leakage_group_id)) > 0),
    lineage_status text NOT NULL DEFAULT 'quarantined'
        CHECK (lineage_status IN ('quarantined', 'revoked')),
    training_authorized boolean NOT NULL DEFAULT false
        CHECK (training_authorized = false),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz,
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.kcm_training_scope_state(tenant_id, user_id)
        ON DELETE CASCADE,
    UNIQUE (tenant_id, user_id, dataset_id, dataset_version, assessment_id),
    UNIQUE (tenant_id, user_id, dataset_id, dataset_version, source_event_id, source_revision),
    CHECK (
        (lineage_status = 'quarantined' AND revoked_at IS NULL)
        OR (lineage_status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

CREATE INDEX kcm_lineage_source_scope_idx
    ON public.kcm_dataset_source_lineage
    (tenant_id, user_id, source_event_id, source_revision);
CREATE INDEX kcm_lineage_dataset_scope_idx
    ON public.kcm_dataset_source_lineage
    (tenant_id, user_id, dataset_id, dataset_version);

-- A digest-only record survives changes to the source within its owner's
-- retention scope. Both this table and its ancestry cascade on user erasure.
CREATE TABLE public.kcm_training_source_revocations (
    revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    source_revision char(64) NOT NULL
        CHECK (source_revision ~ '^[0-9a-f]{64}$'),
    deletion_epoch bigint NOT NULL CHECK (deletion_epoch > 0),
    reason_code text NOT NULL
        CHECK (reason_code IN (
            'memory_deleted', 'memory_tombstoned', 'memory_superseded',
            'consent_revoked', 'source_invalidated', 'rights_revoked',
            'verification_withdrawn', 'privacy_erasure'
        )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.kcm_training_scope_state(tenant_id, user_id)
        ON DELETE CASCADE,
    UNIQUE (tenant_id, user_id, source_event_id, source_revision),
    UNIQUE (tenant_id, user_id, deletion_epoch)
);

-- Neither clients nor ordinary role grants can mint approval, delete a
-- revocation receipt, or mutate the epoch directly.
REVOKE ALL ON public.kcm_training_scope_state FROM PUBLIC;
REVOKE ALL ON public.kcm_dataset_source_lineage FROM PUBLIC;
REVOKE ALL ON public.kcm_training_source_revocations FROM PUBLIC;

DO $kcm_revoke_roles$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL ON public.kcm_training_scope_state, '
                'public.kcm_dataset_source_lineage, '
                'public.kcm_training_source_revocations FROM %I', role_name
            );
        END IF;
    END LOOP;
END;
$kcm_revoke_roles$;

ALTER TABLE public.kcm_training_scope_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_training_scope_state FORCE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_dataset_source_lineage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_dataset_source_lineage FORCE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_training_source_revocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_training_source_revocations FORCE ROW LEVEL SECURITY;

CREATE POLICY kcm_scope_owner_select
    ON public.kcm_training_scope_state FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY kcm_lineage_owner_select
    ON public.kcm_dataset_source_lineage FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );
CREATE POLICY kcm_revocation_owner_select
    ON public.kcm_training_source_revocations FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- Safe, idempotent provisioning for the trusted host only. No training grant
-- is created. Missing rows remain unavailable rather than implicitly epoch 0.
CREATE FUNCTION kcm_internal.kcm_provision_training_scope(
    p_tenant_id uuid, p_user_id uuid
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $kcm_provision$
DECLARE v_epoch bigint;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       OR p_user_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_user_id', true), '')::uuid
    THEN
        RAISE EXCEPTION 'KCM scope does not match authenticated principal'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.kcm_training_scope_state (tenant_id, user_id)
    VALUES (p_tenant_id, p_user_id)
    ON CONFLICT (tenant_id, user_id) DO NOTHING;
    SELECT deletion_epoch INTO STRICT v_epoch
    FROM public.kcm_training_scope_state
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id;
    RETURN v_epoch;
END;
$kcm_provision$;

-- A source revocation is serialized against the owner epoch row. Repeating
-- the identical source/revision returns its existing epoch without bumping.
-- No training lock is handed out; a later worker must implement its own
-- transactionally held start/promotion fence against this same owner row.
CREATE FUNCTION kcm_internal.kcm_revoke_training_source(
    p_tenant_id uuid,
    p_user_id uuid,
    p_source_event_id uuid,
    p_source_revision char(64),
    p_reason_code text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $kcm_revoke$
DECLARE v_epoch bigint;
        v_existing bigint;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       OR p_user_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_user_id', true), '')::uuid
    THEN
        RAISE EXCEPTION 'KCM revocation scope does not match authenticated principal'
            USING ERRCODE = '42501';
    END IF;

    -- Do not implicitly create a scope if provisioning or retention failed.
    SELECT deletion_epoch INTO v_epoch
    FROM public.kcm_training_scope_state
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'KCM scope unavailable' USING ERRCODE = 'P0002';
    END IF;

    SELECT deletion_epoch INTO v_existing
    FROM public.kcm_training_source_revocations
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
      AND source_event_id = p_source_event_id
      AND source_revision = p_source_revision;
    IF FOUND THEN
        RETURN v_existing;
    END IF;

    UPDATE public.kcm_training_scope_state
    SET deletion_epoch = deletion_epoch + 1,
        updated_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
    RETURNING deletion_epoch INTO STRICT v_epoch;

    INSERT INTO public.kcm_training_source_revocations (
        tenant_id, user_id, source_event_id, source_revision,
        deletion_epoch, reason_code
    ) VALUES (
        p_tenant_id, p_user_id, p_source_event_id,
        p_source_revision, v_epoch, p_reason_code
    );

    UPDATE public.kcm_dataset_source_lineage
    SET lineage_status = 'revoked',
        revoked_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
      AND source_event_id = p_source_event_id
      AND source_revision = p_source_revision
      AND lineage_status = 'quarantined';

    RETURN v_epoch;
END;
$kcm_revoke$;

-- By default no application role may call either privileged mutation
-- function. Grant to a *dedicated, audited host execution role* in a
-- subsequent review; grants are not silently inferred from tenant RLS.
REVOKE ALL ON FUNCTION kcm_internal.kcm_provision_training_scope(uuid, uuid)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION kcm_internal.kcm_revoke_training_source(
    uuid, uuid, uuid, char(64), text
) FROM PUBLIC;
DO $kcm_function_roles$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA kcm_internal FROM %I', role_name);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION '
                'kcm_internal.kcm_provision_training_scope(uuid,uuid) FROM %I',
                role_name
            );
            EXECUTE format(
                'REVOKE ALL ON FUNCTION '
                'kcm_internal.kcm_revoke_training_source(uuid,uuid,uuid,character(64),text) FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END;
$kcm_function_roles$;

COMMENT ON TABLE public.kcm_training_scope_state IS
    'Derived user-scoped KCM learning-governance deletion watermark. Never authorizes training.';
COMMENT ON TABLE public.kcm_dataset_source_lineage IS
    'Quarantined source-to-dataset ancestry, no raw training examples or execution approval.';
COMMENT ON TABLE public.kcm_training_source_revocations IS
    'Append-only source revocation references for future dataset and checkpoint fencing.';

COMMIT;

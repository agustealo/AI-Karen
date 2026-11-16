-- KCM-01D2B: transactional learning-governance invalidation on canonical
-- NeuroVault, memory consent and privacy-erasure lifecycle mutations.
--
-- KCM does not authorize training: training_authorized remains hard-false.
-- All routines are internal-only and cannot be invoked by browser clients.
-- The original memory ledger and privacy lifecycle remain source authorities.
BEGIN;

-- A scope-wide invalidation is needed even when no source has been registered
-- yet. A later training executor must fence against this monotonic epoch.
CREATE TABLE public.kcm_training_scope_invalidations (
    invalidation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    deletion_epoch bigint NOT NULL CHECK (deletion_epoch > 0),
    reason_code text NOT NULL
        CHECK (reason_code IN ('consent_revoked', 'privacy_erasure')),
    source_record_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES public.kcm_training_scope_state(tenant_id, user_id)
        ON DELETE CASCADE,
    UNIQUE (tenant_id, user_id, deletion_epoch)
);
CREATE INDEX kcm_scope_invalidations_owner_epoch
    ON public.kcm_training_scope_invalidations
    (tenant_id, user_id, deletion_epoch DESC);

REVOKE ALL ON public.kcm_training_scope_invalidations FROM PUBLIC;
DO $kcm_privileges$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL ON public.kcm_training_scope_invalidations FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END;
$kcm_privileges$;

ALTER TABLE public.kcm_training_scope_invalidations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kcm_training_scope_invalidations FORCE ROW LEVEL SECURITY;
CREATE POLICY kcm_scope_invalidation_owner_read
    ON public.kcm_training_scope_invalidations FOR SELECT
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

-- This is the *one* transactional source-revocation mutation function.
-- All automatic lifecycle triggers and the original host-only entrypoint
-- delegate here. No new grant is created by any of these functions.
CREATE FUNCTION kcm_internal.kcm_record_source_revocation(
    p_tenant_id uuid,
    p_user_id uuid,
    p_source_event_id uuid,
    p_source_revision char(64),
    p_reason_code text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_record$
DECLARE
    v_epoch bigint;
    v_existing bigint;
BEGIN
    IF p_tenant_id IS NULL OR p_user_id IS NULL
       OR p_source_event_id IS NULL
       OR p_source_revision !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'Invalid KCM source identity or revision'
            USING ERRCODE = '23514';
    END IF;

    SELECT deletion_epoch INTO v_epoch
    FROM public.kcm_training_scope_state
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        -- No provisioned KCM source/dataset can exist without this row.
        -- Preserve canonical memory deletion; never invent an epoch of zero.
        RETURN NULL;
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
$kcm_record$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_record_source_revocation(
    uuid, uuid, uuid, char(64), text
) FROM PUBLIC;

-- Retain the original direct host function contract and principal checks.
-- The only change is delegation to the canonical mutation implementation.
CREATE OR REPLACE FUNCTION kcm_internal.kcm_revoke_training_source(
    p_tenant_id uuid,
    p_user_id uuid,
    p_source_event_id uuid,
    p_source_revision char(64),
    p_reason_code text
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_host_revoke$
DECLARE v_epoch bigint;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
       OR p_user_id IS DISTINCT FROM
        NULLIF(current_setting('app.current_user_id', true), '')::uuid
    THEN
        RAISE EXCEPTION 'KCM revocation scope does not match authenticated principal'
            USING ERRCODE = '42501';
    END IF;

    v_epoch := kcm_internal.kcm_record_source_revocation(
        p_tenant_id, p_user_id, p_source_event_id,
        p_source_revision, p_reason_code
    );
    IF v_epoch IS NULL THEN
        RAISE EXCEPTION 'KCM scope unavailable' USING ERRCODE = 'P0002';
    END IF;
    RETURN v_epoch;
END;
$kcm_host_revoke$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_revoke_training_source(
    uuid, uuid, uuid, char(64), text
) FROM PUBLIC;

-- Source invalidation is called by the memory ledger itself, not a
-- detached model or application callback. The trigger inherits the ledger's
-- real tenant/user identity, so transaction contexts without user_id work.
CREATE FUNCTION kcm_internal.kcm_memory_event_invalidation()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_memory$
DECLARE v_old public.memory_event%ROWTYPE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.supersedes IS NOT NULL THEN
            SELECT * INTO v_old FROM public.memory_event
            WHERE event_id = NEW.supersedes
              AND tenant_id = NEW.tenant_id AND user_id = NEW.user_id;
            IF FOUND AND v_old.event_type = 'memory_persisted'
               AND v_old.payload_hash ~ '^[0-9a-f]{64}$'
            THEN
                PERFORM kcm_internal.kcm_record_source_revocation(
                    v_old.tenant_id, v_old.user_id, v_old.event_id,
                    v_old.payload_hash, 'memory_superseded'
                );
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.event_type <> 'memory_persisted'
       OR OLD.payload_hash !~ '^[0-9a-f]{64}$'
    THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        PERFORM kcm_internal.kcm_record_source_revocation(
            OLD.tenant_id, OLD.user_id, OLD.event_id,
            OLD.payload_hash, 'memory_deleted'
        );
        RETURN OLD;
    END IF;

    IF OLD.valid_to IS DISTINCT FROM NEW.valid_to
       OR OLD.consent_state IS DISTINCT FROM NEW.consent_state
       OR OLD.payload_hash IS DISTINCT FROM NEW.payload_hash
       OR OLD.payload IS DISTINCT FROM NEW.payload
       OR OLD.sensitivity_class IS DISTINCT FROM NEW.sensitivity_class
       OR OLD.supersedes IS DISTINCT FROM NEW.supersedes
       OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.user_id IS DISTINCT FROM NEW.user_id
    THEN
        PERFORM kcm_internal.kcm_record_source_revocation(
            OLD.tenant_id, OLD.user_id, OLD.event_id,
            OLD.payload_hash,
            CASE
                WHEN NEW.valid_to IS NOT NULL THEN 'memory_tombstoned'
                ELSE 'source_invalidated'
            END
        );
    END IF;
    RETURN NEW;
END;
$kcm_memory$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_memory_event_invalidation()
    FROM PUBLIC;

CREATE TRIGGER kcm_memory_source_invalidation
    AFTER INSERT OR UPDATE OR DELETE ON public.memory_event
    FOR EACH ROW EXECUTE FUNCTION
    kcm_internal.kcm_memory_event_invalidation();

-- Revoking a consent scope invalidates all existing KCM source ancestry for
-- its owner, even if the scope was not named "kcm.training.*": memory-specific
-- consent scopes are user-configurable. This conservative behavior avoids
-- silently retaining training candidates tied to a withdrawn permission.
CREATE FUNCTION kcm_internal.kcm_invalidate_owner_training(
    p_tenant_id uuid,
    p_user_id uuid,
    p_reason_code text,
    p_source_record_id uuid
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_invalidate$
DECLARE
    v_epoch bigint;
    v_source record;
BEGIN
    IF p_reason_code NOT IN ('consent_revoked', 'privacy_erasure') THEN
        RAISE EXCEPTION 'Invalid KCM scope invalidation reason'
            USING ERRCODE = '23514';
    END IF;

    SELECT deletion_epoch INTO v_epoch
    FROM public.kcm_training_scope_state
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    UPDATE public.kcm_training_scope_state
    SET deletion_epoch = deletion_epoch + 1,
        updated_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND user_id = p_user_id
    RETURNING deletion_epoch INTO STRICT v_epoch;

    INSERT INTO public.kcm_training_scope_invalidations (
        tenant_id, user_id, deletion_epoch, reason_code, source_record_id
    ) VALUES (
        p_tenant_id, p_user_id, v_epoch, p_reason_code, p_source_record_id
    );

    FOR v_source IN
        SELECT DISTINCT source_event_id, source_revision
        FROM public.kcm_dataset_source_lineage
        WHERE tenant_id = p_tenant_id AND user_id = p_user_id
          AND lineage_status = 'quarantined'
        ORDER BY source_event_id, source_revision
    LOOP
        PERFORM kcm_internal.kcm_record_source_revocation(
            p_tenant_id, p_user_id,
            v_source.source_event_id, v_source.source_revision,
            p_reason_code
        );
    END LOOP;
    RETURN v_epoch;
END;
$kcm_invalidate$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_invalidate_owner_training(
    uuid, uuid, text, uuid
) FROM PUBLIC;

CREATE FUNCTION kcm_internal.kcm_consent_scope_invalidation()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_consent$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_granted IS TRUE THEN
            PERFORM kcm_internal.kcm_invalidate_owner_training(
                OLD.tenant_id, OLD.user_id,
                'consent_revoked', OLD.scope_id
            );
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND (
        (OLD.is_granted IS TRUE AND NEW.is_granted IS NOT TRUE)
        OR (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL)
        OR OLD.scope_name IS DISTINCT FROM NEW.scope_name
        OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
        OR OLD.user_id IS DISTINCT FROM NEW.user_id
    ) THEN
        PERFORM kcm_internal.kcm_invalidate_owner_training(
            OLD.tenant_id, OLD.user_id,
            'consent_revoked', OLD.scope_id
        );
    END IF;

    RETURN NEW;
END;
$kcm_consent$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_consent_scope_invalidation()
    FROM PUBLIC;
CREATE TRIGGER kcm_consent_training_invalidation
    AFTER UPDATE OR DELETE ON public.consent_scope
    FOR EACH ROW EXECUTE FUNCTION
    kcm_internal.kcm_consent_scope_invalidation();

-- Erasure must fence training candidates as soon as the actual privacy
-- lifecycle begins, not only when the physical memory deletion completes.
CREATE FUNCTION kcm_internal.kcm_privacy_erasure_invalidation()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog AS $kcm_privacy$
BEGIN
    IF NEW.request_type = 'erasure'
       AND NEW.status IN ('in_progress', 'completed')
       AND (
           TG_OP = 'INSERT'
           OR OLD.status IS DISTINCT FROM NEW.status
       )
    THEN
        PERFORM kcm_internal.kcm_invalidate_owner_training(
            NEW.tenant_id, NEW.user_id, 'privacy_erasure', NEW.request_id
        );
    END IF;
    RETURN NEW;
END;
$kcm_privacy$;

REVOKE ALL ON FUNCTION kcm_internal.kcm_privacy_erasure_invalidation()
    FROM PUBLIC;
CREATE TRIGGER kcm_privacy_erasure_training_invalidation
    AFTER INSERT OR UPDATE ON public.privacy_requests
    FOR EACH ROW EXECUTE FUNCTION
    kcm_internal.kcm_privacy_erasure_invalidation();

COMMENT ON TABLE public.kcm_training_scope_invalidations IS
    'Owner-scoped irreversible learning-source invalidation audit; no training approval.';
COMMENT ON FUNCTION kcm_internal.kcm_memory_event_invalidation() IS
    'Atomic derivative KCM source fencing inside canonical NeuroVault memory mutations.';
COMMENT ON FUNCTION kcm_internal.kcm_consent_scope_invalidation() IS
    'Conservatively invalidates KCM ancestry when authenticated memory consent is withdrawn.';
COMMENT ON FUNCTION kcm_internal.kcm_privacy_erasure_invalidation() IS
    'Invalidates KCM ancestry on durable privacy erasure lifecycle transition.';

COMMIT;

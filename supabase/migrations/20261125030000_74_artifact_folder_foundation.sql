-- KEXP-004B.2A: private logical folders; no file association or API activation.
BEGIN;

-- The canonical user identity is already globally unique. This additional
-- constraint permits a foreign key that also proves tenant ownership.
ALTER TABLE public.auth_users
    ADD CONSTRAINT uq_auth_users_tenant_user_folder_scope UNIQUE (tenant_id, user_id);

CREATE TABLE public.artifact_folders (
    folder_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    owner_user_id UUID NOT NULL,
    parent_folder_id UUID,
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 256 AND name = btrim(name) AND name !~ '[[:cntrl:]]'),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision BETWEEN 1 AND 9223372036854775806),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_artifact_folder_scope UNIQUE (tenant_id, owner_user_id, folder_id),
    CONSTRAINT fk_artifact_folder_owner FOREIGN KEY (tenant_id, owner_user_id)
        REFERENCES public.auth_users (tenant_id, user_id) ON DELETE CASCADE,
    CONSTRAINT fk_artifact_folder_parent FOREIGN KEY (tenant_id, owner_user_id, parent_folder_id)
        REFERENCES public.artifact_folders (tenant_id, owner_user_id, folder_id),
    CONSTRAINT ck_artifact_folder_not_self CHECK (parent_folder_id IS DISTINCT FROM folder_id)
);

CREATE INDEX idx_artifact_folder_children
    ON public.artifact_folders (tenant_id, owner_user_id, parent_folder_id, name, folder_id);

-- Require an existing parent at INSERT time, rather than relying only on
-- statement-end FK checks (which permit cycles in multi-row INSERTs).
-- Parent changes are disabled until governed movement is implemented.
CREATE FUNCTION public.guard_artifact_folder_identity() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.folder_id, NEW.tenant_id, NEW.owner_user_id, NEW.parent_folder_id)
            IS DISTINCT FROM ROW(OLD.folder_id, OLD.tenant_id, OLD.owner_user_id, OLD.parent_folder_id) THEN
            RAISE EXCEPTION 'artifact_folder_identity_immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.parent_folder_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.artifact_folders AS p
            WHERE p.folder_id = NEW.parent_folder_id
              AND p.tenant_id = NEW.tenant_id
              AND p.owner_user_id = NEW.owner_user_id
        ) THEN
            RAISE EXCEPTION 'artifact_folder_parent_unavailable' USING ERRCODE = '23503';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER artifact_folder_identity_guard
    BEFORE INSERT OR UPDATE ON public.artifact_folders
    FOR EACH ROW EXECUTE FUNCTION public.guard_artifact_folder_identity();
REVOKE ALL ON FUNCTION public.guard_artifact_folder_identity() FROM PUBLIC;
ALTER TABLE public.artifact_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_folders FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.artifact_folders FROM PUBLIC, anon, authenticated;
-- No client policies or grants; trusted server operations remain unavailable
-- until the governed repository and actor-scoped admission are implemented.
COMMENT ON TABLE public.artifact_folders IS
    'Private logical folder metadata. No artifact association or movement in this migration.';
COMMIT;

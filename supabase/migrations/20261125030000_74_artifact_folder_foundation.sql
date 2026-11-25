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
    'Private logical folder metadata. No governed movement API activated.';
-- Folder assignment is organization metadata, not a content revision.
-- Existing rows remain at root. On folder deletion retain the artifact.
ALTER TABLE public.files
    ADD COLUMN folder_id UUID,
    ADD COLUMN organization_revision BIGINT NOT NULL DEFAULT 1
        CHECK (organization_revision BETWEEN 1 AND 9223372036854775806),
    ADD CONSTRAINT ck_file_folder_owner_present CHECK (
        folder_id IS NULL OR (tenant_id IS NOT NULL AND owner_user_id IS NOT NULL)
    ),
    ADD CONSTRAINT fk_file_owned_folder
        FOREIGN KEY (tenant_id, owner_user_id, folder_id)
        REFERENCES public.artifact_folders (tenant_id, owner_user_id, folder_id)
        ON DELETE SET NULL (folder_id);

CREATE INDEX idx_files_owner_folder_page
    ON public.files (tenant_id, owner_user_id, folder_id, created_at DESC, file_id DESC)
    WHERE deleted_at IS NULL;

-- Account deletion can null the file owner before cascading folder deletion.
-- Clear the association in that same row update, independent of FK trigger order.
CREATE FUNCTION public.guard_file_folder_organization() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.owner_user_id IS NULL AND OLD.owner_user_id IS NOT NULL THEN
            NEW.folder_id := NULL;
        END IF;
        IF NEW.folder_id IS DISTINCT FROM OLD.folder_id THEN
            NEW.organization_revision := OLD.organization_revision + 1;
        ELSIF NEW.organization_revision IS DISTINCT FROM OLD.organization_revision THEN
            RAISE EXCEPTION 'artifact_organization_revision_managed' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.organization_revision <> 1 THEN
        RAISE EXCEPTION 'artifact_organization_revision_invalid' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$;
CREATE TRIGGER file_folder_organization_guard
    BEFORE INSERT OR UPDATE ON public.files
    FOR EACH ROW EXECUTE FUNCTION public.guard_file_folder_organization();
REVOKE ALL ON FUNCTION public.guard_file_folder_organization() FROM PUBLIC;

COMMENT ON COLUMN public.files.folder_id IS
    'Logical organization only; NULL is root. Not a content access grant.';
COMMENT ON COLUMN public.files.organization_revision IS
    'Database-managed folder assignment revision; not SHA-256 content revision. Governed CAS API pending.';

COMMIT;

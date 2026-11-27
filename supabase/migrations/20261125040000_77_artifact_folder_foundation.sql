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

-- Every folder mutation updates the same owner-scoped fence row. Unlike
-- advisory locks alone, this forces a serialization failure under a stale
-- repeatable-read snapshot. Fence rows have the same account lifecycle.
CREATE TABLE public.artifact_folder_mutation_fences (
    tenant_id UUID NOT NULL,
    owner_user_id UUID NOT NULL,
    generation BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, owner_user_id),
    FOREIGN KEY (tenant_id, owner_user_id)
        REFERENCES public.auth_users (tenant_id, user_id) ON DELETE CASCADE
);
ALTER TABLE public.artifact_folder_mutation_fences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_folder_mutation_fences FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.artifact_folder_mutation_fences FROM PUBLIC;

CREATE FUNCTION public.guard_artifact_folder_identity() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    cycle_found BOOLEAN;
    parent_root_found BOOLEAN;
    parent_depth BIGINT := 0;
    subtree_too_deep BOOLEAN;
    -- Root is depth one; keep this storage invariant aligned with the
    -- bounded breadcrumb reader in SupabaseArtifactStore.
    max_depth CONSTANT INTEGER := 64;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.folder_id, NEW.tenant_id, NEW.owner_user_id, NEW.created_at)
            IS DISTINCT FROM ROW(OLD.folder_id, OLD.tenant_id, OLD.owner_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'artifact_folder_identity_immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.revision IS DISTINCT FROM OLD.revision THEN
            RAISE EXCEPTION 'artifact_folder_revision_managed' USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.parent_folder_id, NEW.name) IS NOT DISTINCT FROM ROW(OLD.parent_folder_id, OLD.name) THEN
            NEW.updated_at := OLD.updated_at;
            RETURN NEW;
        END IF;
        NEW.revision := OLD.revision + 1;
        NEW.updated_at := clock_timestamp();
    ELSIF NEW.revision <> 1 THEN
        RAISE EXCEPTION 'artifact_folder_initial_revision_invalid' USING ERRCODE = '23514';
    END IF;

    -- Depth proof requires the entire owner hierarchy, not an RLS-filtered
    -- view. The existing repository admits only this trusted server scope.
    IF row_security_active('public.artifact_folders'::regclass) THEN
        RAISE EXCEPTION 'artifact_folder_hierarchy_scope_unavailable' USING ERRCODE = '42501';
    END IF;

    INSERT INTO public.artifact_folder_mutation_fences AS fence (tenant_id, owner_user_id)
    VALUES (NEW.tenant_id, NEW.owner_user_id)
    ON CONFLICT (tenant_id, owner_user_id) DO UPDATE SET generation = fence.generation + 1;

    IF NEW.parent_folder_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.artifact_folders AS p
            WHERE p.folder_id = NEW.parent_folder_id
              AND p.tenant_id = NEW.tenant_id
              AND p.owner_user_id = NEW.owner_user_id
        ) THEN
            RAISE EXCEPTION 'artifact_folder_parent_unavailable' USING ERRCODE = '23503';
        END IF;
        WITH RECURSIVE ancestry(folder_id, parent_folder_id) AS (
            SELECT f.folder_id, f.parent_folder_id FROM public.artifact_folders f
            WHERE f.folder_id = NEW.parent_folder_id
              AND f.tenant_id = NEW.tenant_id AND f.owner_user_id = NEW.owner_user_id
            UNION
            SELECT f.folder_id, f.parent_folder_id FROM public.artifact_folders f
            JOIN ancestry a ON f.folder_id = a.parent_folder_id
            WHERE f.tenant_id = NEW.tenant_id AND f.owner_user_id = NEW.owner_user_id
        )
        SELECT COALESCE(bool_or(folder_id = NEW.folder_id), FALSE),
               count(*), COALESCE(bool_or(parent_folder_id IS NULL), FALSE)
        INTO cycle_found, parent_depth, parent_root_found
        FROM ancestry;
        IF cycle_found OR NOT parent_root_found THEN
            RAISE EXCEPTION 'artifact_folder_cycle' USING ERRCODE = '23514';
        END IF;
        IF parent_depth >= max_depth THEN
            RAISE EXCEPTION 'artifact_folder_depth_exceeded' USING ERRCODE = '23514';
        END IF;
    END IF;

    -- Creation has no descendants. A move must also fit its deepest
    -- descendant, including when moved to root. Read after the owner fence
    -- so concurrent create/move operations cannot validate stale topology.
    IF TG_OP = 'UPDATE' AND NEW.parent_folder_id IS DISTINCT FROM OLD.parent_folder_id THEN
        WITH RECURSIVE descendants(folder_id, depth) AS (
            SELECT NEW.folder_id, 1
            UNION ALL
            SELECT f.folder_id, d.depth + 1
            FROM public.artifact_folders f
            JOIN descendants d ON f.parent_folder_id = d.folder_id
            WHERE f.tenant_id = NEW.tenant_id AND f.owner_user_id = NEW.owner_user_id
              AND d.depth <= max_depth - parent_depth
        )
        SELECT EXISTS (SELECT 1 FROM descendants WHERE depth > max_depth - parent_depth)
        INTO subtree_too_deep;
        IF subtree_too_deep THEN
            RAISE EXCEPTION 'artifact_folder_depth_exceeded' USING ERRCODE = '23514';
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
REVOKE ALL ON public.artifact_folders FROM PUBLIC;
-- No client policies or grants; trusted server operations remain unavailable
-- until the governed repository and actor-scoped admission are implemented.
COMMENT ON TABLE public.artifact_folders IS
    'Private logical folder metadata. No governed movement API activated.';
-- Internal CAS contract. No public API grant. A null result represents a
-- missing, foreign, or stale source without disclosing its existence.
CREATE FUNCTION public.move_owned_artifact_folder(
    p_tenant UUID, p_owner UUID, p_folder UUID, p_parent UUID, p_revision BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    resulting_revision BIGINT;
BEGIN
    IF p_tenant IS NULL OR p_owner IS NULL OR p_folder IS NULL OR p_revision IS NULL OR p_revision < 1 THEN
        RAISE EXCEPTION 'artifact_folder_move_invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.artifact_folders
    SET parent_folder_id = p_parent
    WHERE tenant_id = p_tenant AND owner_user_id = p_owner
      AND folder_id = p_folder AND revision = p_revision
    RETURNING revision INTO resulting_revision;
    RETURN resulting_revision;
END;
$$;
REVOKE ALL ON FUNCTION public.move_owned_artifact_folder(UUID, UUID, UUID, UUID, BIGINT)
    FROM PUBLIC;

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
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
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
$$;
CREATE TRIGGER file_folder_organization_guard
    BEFORE INSERT OR UPDATE ON public.files
    FOR EACH ROW EXECUTE FUNCTION public.guard_file_folder_organization();
REVOKE ALL ON FUNCTION public.guard_file_folder_organization() FROM PUBLIC;

COMMENT ON COLUMN public.files.folder_id IS
    'Logical organization only; NULL is root. Not a content access grant.';
COMMENT ON COLUMN public.files.organization_revision IS
    'Database-managed folder assignment revision; not SHA-256 content revision. Governed CAS API pending.';

-- The owner-facing delete contract is deliberately stricter than the FK's
-- administrative/account cleanup behavior. A full reference index includes
-- archived files, which must prevent an empty-folder deletion too.
CREATE INDEX idx_files_owned_folder_references
    ON public.files (tenant_id, owner_user_id, folder_id)
    WHERE folder_id IS NOT NULL;

CREATE FUNCTION public.delete_empty_owned_artifact_folder(
    p_tenant UUID, p_owner UUID, p_folder UUID, p_revision BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF p_tenant IS NULL OR p_owner IS NULL OR p_folder IS NULL
       OR p_revision IS NULL OR p_revision NOT BETWEEN 1 AND 9223372036854775806 THEN
        RAISE EXCEPTION 'artifact_folder_delete_invalid' USING ERRCODE = '22023';
    END IF;
    -- Fresh statement snapshots after the row lock are essential. Do not
    -- accept a stale repeatable-read snapshot or filtered reference inventory.
    IF current_setting('transaction_isolation') <> 'read committed'
       OR row_security_active('public.files'::regclass)
       OR row_security_active('public.artifact_folders'::regclass) THEN
        RAISE EXCEPTION 'artifact_folder_delete_scope_unavailable' USING ERRCODE = '42501';
    END IF;
    -- This conflicts with the FK's key-share lock on a destination folder.
    -- If an assignment wins, the following statement sees it; if deletion
    -- wins, a waiting assignment fails its FK instead of silently detaching.
    PERFORM 1 FROM public.artifact_folders
    WHERE tenant_id = p_tenant AND owner_user_id = p_owner
      AND folder_id = p_folder AND revision = p_revision
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.artifact_folders
        WHERE tenant_id = p_tenant AND owner_user_id = p_owner AND parent_folder_id = p_folder
    ) OR EXISTS (
        SELECT 1 FROM public.files
        WHERE tenant_id = p_tenant AND owner_user_id = p_owner AND folder_id = p_folder
    ) THEN
        RETURN FALSE;
    END IF;
    DELETE FROM public.artifact_folders
    WHERE tenant_id = p_tenant AND owner_user_id = p_owner
      AND folder_id = p_folder AND revision = p_revision;
    RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION public.delete_empty_owned_artifact_folder(UUID, UUID, UUID, BIGINT)
    FROM PUBLIC;

-- Supabase roles exist in managed installations but not every local PostgreSQL
-- cluster. Always revoke PUBLIC above; revoke each existing named role here.
-- Do not create roles or grant privileges as a side effect of this migration.
DO $artifact_folder_private_revoke$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON public.artifact_folder_mutation_fences FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON public.artifact_folders FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION public.move_owned_artifact_folder(UUID, UUID, UUID, UUID, BIGINT) FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION public.delete_empty_owned_artifact_folder(UUID, UUID, UUID, BIGINT) FROM %I', role_name);
        END IF;
    END LOOP;
END
$artifact_folder_private_revoke$;

COMMIT;

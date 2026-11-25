-- Run against disposable migrated PostgreSQL as the trusted migration role.
-- All synthetic fixtures roll back. No production data.
BEGIN;
INSERT INTO public.tenants(id,name,slug) VALUES
('a0000000-0000-4000-8000-000000000001','Folder test A','folder-test-a'),
('a0000000-0000-4000-8000-000000000002','Folder test B','folder-test-b');
INSERT INTO public.auth_users(user_id,tenant_id,email,roles) VALUES
('b0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000001','folder-a@example.invalid','[]'),
('b0000000-0000-4000-8000-000000000002','a0000000-0000-4000-8000-000000000001','folder-b@example.invalid','[]'),
('b0000000-0000-4000-8000-000000000003','a0000000-0000-4000-8000-000000000002','folder-c@example.invalid','[]');
INSERT INTO public.artifact_folders(folder_id,tenant_id,owner_user_id,name) VALUES
('c0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000001','Root');
INSERT INTO public.artifact_folders(folder_id,tenant_id,owner_user_id,parent_folder_id,name) VALUES
('c0000000-0000-4000-8000-000000000002','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000001','c0000000-0000-4000-8000-000000000001','Child');
DO $$
BEGIN
    BEGIN
        INSERT INTO public.artifact_folders(tenant_id,owner_user_id,parent_folder_id,name)
        VALUES ('a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000002','c0000000-0000-4000-8000-000000000001','Foreign');
        RAISE EXCEPTION 'cross-owner parent accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.artifact_folders(tenant_id,owner_user_id,parent_folder_id,name)
        VALUES ('a0000000-0000-4000-8000-000000000002','b0000000-0000-4000-8000-000000000003','c0000000-0000-4000-8000-000000000001','Foreign');
        RAISE EXCEPTION 'cross-tenant parent accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.artifact_folders SET parent_folder_id='c0000000-0000-4000-8000-000000000002'
        WHERE folder_id='c0000000-0000-4000-8000-000000000001';
        RAISE EXCEPTION 'cycle accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.artifact_folders(folder_id,tenant_id,owner_user_id,parent_folder_id,name)
        VALUES ('c0000000-0000-4000-8000-000000000003','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000001','c0000000-0000-4000-8000-000000000004','Cycle A'),
        ('c0000000-0000-4000-8000-000000000004','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000001','c0000000-0000-4000-8000-000000000003','Cycle B');
        RAISE EXCEPTION 'multi-row cycle accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    IF has_table_privilege('anon','public.artifact_folders','SELECT')
       OR has_table_privilege('authenticated','public.artifact_folders','INSERT') THEN
        RAISE EXCEPTION 'unexpected client privilege';
    END IF;
END;
$$;
-- Exercise the internal CAS contract without exposing an API.
DO $$
DECLARE
    tenant UUID := 'a0000000-0000-4000-8000-000000000001';
    owner_id UUID := 'b0000000-0000-4000-8000-000000000001';
    root_id UUID := 'c0000000-0000-4000-8000-000000000001';
    child_id UUID := 'c0000000-0000-4000-8000-000000000002';
BEGIN
    IF public.move_owned_artifact_folder(tenant, owner_id, child_id, NULL, 1) IS DISTINCT FROM 2::bigint THEN
        RAISE EXCEPTION 'root move did not advance revision';
    END IF;
    IF public.move_owned_artifact_folder(tenant, owner_id, child_id, root_id, 1) IS NOT NULL THEN
        RAISE EXCEPTION 'stale revision accepted';
    END IF;
    IF public.move_owned_artifact_folder(tenant, owner_id, child_id, root_id, 2) IS DISTINCT FROM 3::bigint THEN
        RAISE EXCEPTION 'valid reparent failed';
    END IF;
    IF public.move_owned_artifact_folder(tenant, owner_id, child_id, root_id, 3) IS DISTINCT FROM 3::bigint THEN
        RAISE EXCEPTION 'no-op advanced revision';
    END IF;
    BEGIN
        PERFORM public.move_owned_artifact_folder(tenant, owner_id, root_id, child_id, 1);
        RAISE EXCEPTION 'descendant move accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    IF public.move_owned_artifact_folder(tenant, 'b0000000-0000-4000-8000-000000000002', child_id, NULL, 3) IS NOT NULL THEN
        RAISE EXCEPTION 'foreign source disclosed';
    END IF;
    IF has_function_privilege('authenticated','public.move_owned_artifact_folder(uuid,uuid,uuid,uuid,bigint)','EXECUTE') THEN
        RAISE EXCEPTION 'client movement privilege granted';
    END IF;
END;
$$;
-- Existing artifact identity and storage remain intact across organization changes.
INSERT INTO public.files(file_id,tenant_id,owner_user_id,name,storage_uri,sha256,folder_id)
VALUES ('folder-proof-file','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000001','proof.txt','fixture://proof',repeat('a',64),'c0000000-0000-4000-8000-000000000002'),
('folder-proof-foreign','a0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000002','foreign.txt','fixture://foreign',repeat('b',64),NULL);
DO $$ BEGIN
    BEGIN
        UPDATE public.files SET folder_id='c0000000-0000-4000-8000-000000000001'
        WHERE file_id='folder-proof-foreign';
        RAISE EXCEPTION 'foreign folder assignment accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.files SET organization_revision=999 WHERE file_id='folder-proof-file';
        RAISE EXCEPTION 'forged revision accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;
UPDATE public.files SET deleted_at=now() WHERE file_id='folder-proof-file';
UPDATE public.files SET deleted_at=NULL WHERE file_id='folder-proof-file';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.files WHERE file_id='folder-proof-file'
        AND folder_id='c0000000-0000-4000-8000-000000000002'
        AND organization_revision=1 AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'archive restore changed organization';
    END IF;
END $$;
DELETE FROM public.artifact_folders WHERE folder_id='c0000000-0000-4000-8000-000000000002';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.files WHERE file_id='folder-proof-file'
        AND folder_id IS NULL AND organization_revision=2
        AND storage_uri='fixture://proof' AND sha256=repeat('a',64)) THEN
        RAISE EXCEPTION 'folder deletion did not preserve artifact';
    END IF;
END $$;
UPDATE public.files SET folder_id='c0000000-0000-4000-8000-000000000001'
WHERE file_id='folder-proof-file';
DELETE FROM public.auth_users WHERE user_id='b0000000-0000-4000-8000-000000000001';
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM public.artifact_folders WHERE owner_user_id='b0000000-0000-4000-8000-000000000001') THEN
        RAISE EXCEPTION 'folder cleanup failed';
    END IF;
END $$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.files WHERE file_id='folder-proof-file'
        AND owner_user_id IS NULL AND folder_id IS NULL AND organization_revision=4
        AND tenant_id='a0000000-0000-4000-8000-000000000001'
        AND storage_uri='fixture://proof' AND sha256=repeat('a',64)) THEN
        RAISE EXCEPTION 'account deletion changed retained artifact or left folder reference';
    END IF;
END $$;
ROLLBACK;

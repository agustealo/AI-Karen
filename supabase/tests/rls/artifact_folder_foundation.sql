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
DELETE FROM public.auth_users WHERE user_id='b0000000-0000-4000-8000-000000000001';
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM public.artifact_folders WHERE owner_user_id='b0000000-0000-4000-8000-000000000001') THEN
        RAISE EXCEPTION 'folder cleanup failed';
    END IF;
END $$;
ROLLBACK;

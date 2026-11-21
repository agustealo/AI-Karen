-- CK-GEN-01D2: Restore the canonical ArtifactStore archive-state contract.
--
-- The original files table in 20260827010000_01_core_persona_runtime.sql
-- has no deleted_at column, but the existing SupabaseArtifactStore archive,
-- restore, archived listing and owner-scoped read methods all use it.
-- Add only the missing nullable state; do not change owner/tenant permissions,
-- RLS, storage keys, artifact contents or existing record visibility.
BEGIN;

ALTER TABLE public.files
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

COMMIT;

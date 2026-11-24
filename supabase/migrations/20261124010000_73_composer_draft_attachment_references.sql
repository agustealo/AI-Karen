-- KUI-004B3.1: revision-bound metadata references, not content admission.
BEGIN;
ALTER TABLE public.conversation_composer_drafts
    ADD COLUMN attachment_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT ck_composer_attachment_references_array CHECK (
        CASE WHEN jsonb_typeof(attachment_references) = 'array'
             THEN jsonb_array_length(attachment_references) <= 12
             ELSE false END
    );
COMMENT ON COLUMN public.conversation_composer_drafts.attachment_references IS
    'Unsent owner-validated source_id and SHA-256 revision references; shares draft CAS revision; not authorization to read content.';
COMMIT;

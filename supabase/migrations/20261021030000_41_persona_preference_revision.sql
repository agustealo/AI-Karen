-- Revision fencing for concurrent persona preference edits.
-- Forward-only addition; defaults preserve legacy rows.
ALTER TABLE public.user_persona_preferences
  ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.user_persona_preferences
  ADD CONSTRAINT user_persona_preferences_revision_nonnegative CHECK (revision >= 0);

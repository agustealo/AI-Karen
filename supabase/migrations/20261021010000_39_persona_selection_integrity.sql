-- Forward-only persona selection integrity: built-in identifiers and scoped custom IDs.
-- The baseline FK only references custom_personas and prevents selecting built-ins.
-- Preserve cross-user/tenant isolation via a database-level validation trigger.

ALTER TABLE public.user_persona_preferences
    DROP CONSTRAINT IF EXISTS fk_user_persona_preferences_active_persona;

CREATE OR REPLACE FUNCTION public.validate_persona_selection()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.active_persona_id IS NULL
       OR NEW.active_persona_id IN ('assistant', 'expert', 'creative') THEN
        RETURN NEW;
    END IF;

    PERFORM 1
    FROM public.custom_personas
    WHERE id = NEW.active_persona_id
      AND tenant_id = NEW.tenant_id
      AND user_id = NEW.user_id
      AND is_active = TRUE
    FOR KEY SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Selected persona is unavailable'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_persona_selection
    ON public.user_persona_preferences;
CREATE TRIGGER trg_validate_persona_selection
    BEFORE INSERT OR UPDATE OF active_persona_id, tenant_id, user_id
    ON public.user_persona_preferences
    FOR EACH ROW EXECUTE FUNCTION public.validate_persona_selection();

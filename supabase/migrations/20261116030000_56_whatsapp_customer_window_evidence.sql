-- KWA-01C2: signed WhatsApp customer-message time for host-owned dispatch policy.
-- Nullable for legacy inbox and non-WhatsApp providers; NULL cannot authorize
-- WhatsApp free-form sends. No native body, tokens, or customer PII is added.
BEGIN;

ALTER TABLE public.channel_inbox
    ADD COLUMN IF NOT EXISTS provider_event_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_channel_inbox_provider_window
    ON public.channel_inbox (
        tenant_id, connection_id, connection_revision,
        external_sender_id, provider_event_at DESC
    )
    WHERE provider_event_at IS NOT NULL;

CREATE OR REPLACE FUNCTION public.channel_inbox_provider_time_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.provider_event_at IS DISTINCT FROM OLD.provider_event_at THEN
        RAISE EXCEPTION 'Provider message time is immutable after admission';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_channel_inbox_provider_time_immutable
    ON public.channel_inbox;
CREATE TRIGGER trg_channel_inbox_provider_time_immutable
    BEFORE UPDATE ON public.channel_inbox
    FOR EACH ROW
    EXECUTE FUNCTION public.channel_inbox_provider_time_immutable();

COMMENT ON COLUMN public.channel_inbox.provider_event_at IS
    'Signed provider customer-message timestamp. Immutable; missing evidence denies WhatsApp text dispatch.';

COMMIT;

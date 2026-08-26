-- PROD-READY-1E: durable refresh-token rotation and replay detection.
--
-- auth_sessions remains the canonical live-session authority. This table only
-- records hashes of refresh tokens after they have been consumed by rotation.
-- No raw historical refresh token is persisted here.

CREATE TABLE IF NOT EXISTS public.auth_refresh_token_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES public.auth_sessions(session_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.auth_users(user_id) ON DELETE CASCADE,
    token_hash varchar(64) NOT NULL UNIQUE,
    rotated_at timestamp without time zone NOT NULL DEFAULT now(),
    replayed_at timestamp without time zone NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_history_session
    ON public.auth_refresh_token_history (session_id, rotated_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_history_user
    ON public.auth_refresh_token_history (user_id, rotated_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_history_token_hash
    ON public.auth_refresh_token_history (token_hash);

COMMENT ON TABLE public.auth_refresh_token_history IS
    'SHA-256 history of consumed refresh tokens used to detect replay. auth_sessions remains the live session authority.';

COMMENT ON COLUMN public.auth_refresh_token_history.token_hash IS
    'SHA-256 digest of a consumed refresh token. Raw historical refresh tokens must never be stored here.';

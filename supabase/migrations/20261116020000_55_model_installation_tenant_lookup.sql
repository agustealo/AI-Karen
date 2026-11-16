-- Model-backed plugins must resolve licensed, completed jobs for the exact
-- authenticated tenant. Migration 42 deliberately keeps legacy NULL tenants
-- admin-only; consumer inference cannot adopt them implicitly.
--
-- This is an index for the existing canonical model-download job authority.
-- It creates no alternate ownership table, role, policy or migration rewrite.
CREATE INDEX IF NOT EXISTS idx_model_download_approved_tenant_installation
    ON public.model_download_jobs (
        tenant_id, model_id, revision, channel_id, created_at DESC
    )
    WHERE tenant_id IS NOT NULL
      AND status = 'completed'
      AND license_accepted IS TRUE
      AND trust_remote_code IS NOT TRUE;

COMMENT ON INDEX public.idx_model_download_approved_tenant_installation IS
    'Host-only tenant-scoped approved model installation eligibility; never grants legacy or cross-tenant jobs.';

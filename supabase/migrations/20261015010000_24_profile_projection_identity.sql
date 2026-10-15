-- MI-04: Canonical current-slot identity for rebuildable profile projections.
-- Governing memory_event and memory_assertion history remains unchanged.
-- Existing unkeyed legacy rows stay intact for explicit future reconciliation;
-- never guess which competing historical profile row should win.
--
-- Deployment order: apply this forward-only schema migration before deploying
-- projector code that writes profile_fact.projection_key.

BEGIN;

ALTER TABLE public.profile_fact
    ADD COLUMN IF NOT EXISTS projection_key varchar(64);

-- A current keyed slot belongs to one fact per tenant/user. Historical rows
-- (valid_to IS NOT NULL) are not constrained, and pre-MI-04 nullable keys
-- are deliberately excluded until safely reconciled from event evidence.
CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_fact_active_projection_key
    ON public.profile_fact (tenant_id, user_id, projection_key)
    WHERE valid_to IS NULL AND projection_key IS NOT NULL;

COMMENT ON COLUMN public.profile_fact.projection_key IS
    'Canonical scoped/cardinality-aware current projection slot. NULL indicates a legacy row pending governed reconciliation; never treat NULL as verified uniqueness.';

COMMIT;

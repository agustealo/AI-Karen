#!/usr/bin/env bash
set -euo pipefail

# Read-only verification against the same database used for canonical migrations.
# Does not inspect or print private drafts or credentials.
: "${DATABASE_URL:?DATABASE_URL is required}"
if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required to prove composer draft schema readiness" >&2
  exit 2
fi

# A schema read is a deployment preflight, not a substitute for authenticated
# conversation ownership and CAS read/write acceptance tests.
PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}" psql "${DATABASE_URL}" \
  -X --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align <<'SQL'
DO $$
DECLARE
    drafts regclass := to_regclass('public.conversation_composer_drafts');
    policy_count integer;
    fk_count integer;
    revision_ok boolean;
    rls_enabled boolean;
    rls_forced boolean;
BEGIN
    IF drafts IS NULL THEN
        RAISE EXCEPTION 'composer_draft_schema_missing: apply canonical migration 47';
    END IF;
    SELECT c.relrowsecurity, c.relforcerowsecurity
      INTO rls_enabled, rls_forced
      FROM pg_class c WHERE c.oid = drafts;
    IF NOT rls_enabled OR NOT rls_forced THEN
        RAISE EXCEPTION 'composer_draft_security_missing: RLS and FORCE RLS are required';
    END IF;
    SELECT count(*) INTO policy_count FROM pg_policies
     WHERE schemaname = 'public' AND tablename = 'conversation_composer_drafts'
       AND policyname = 'conversation_composer_draft_owner';
    IF policy_count <> 1 THEN
        RAISE EXCEPTION 'composer_draft_owner_policy_missing';
    END IF;
    SELECT count(*) INTO fk_count FROM pg_constraint
     WHERE conrelid = drafts AND contype = 'f';
    IF fk_count < 3 THEN
        RAISE EXCEPTION 'composer_draft_foreign_keys_missing';
    END IF;
    SELECT EXISTS (
      SELECT 1 FROM pg_attribute
      WHERE attrelid = drafts AND attname = 'revision'
        AND atttypid = 'bigint'::regtype AND attnotnull
    ) INTO revision_ok;
    IF NOT revision_ok THEN
        RAISE EXCEPTION 'composer_draft_revision_contract_missing';
    END IF;
    RAISE NOTICE 'composer_draft_schema_ready';
END
$$;
SQL

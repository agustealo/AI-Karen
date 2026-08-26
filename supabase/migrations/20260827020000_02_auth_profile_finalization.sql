-- AI KAREN production baseline migration
-- Consolidated pre-production history. Future production changes are forward-only.
-- Source history is preserved in Git and docs/database/BASELINE_2026_08.md.


-- ============================================================================
-- BASELINE SOURCE: 20260823040000_fix_auth_user_schema.sql
-- ============================================================================

﻿-- Migrated from database/migrations/005_fix_auth_user_schema.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration 005: Fix auth_users schema alignment with models
-- Added: 2026-04-13

-- Add missing username column
ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS username TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_user_username ON auth_users(username);

-- Rename last_login_at to last_login to match model
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='auth_users' AND column_name='last_login_at') THEN
        ALTER TABLE auth_users RENAME COLUMN last_login_at TO last_login;
    END IF;
END $$;

-- Ensure tenant_id can store UUIDs (it's currently TEXT in migration 001)
-- SQLAlchemy models expect UUIDs. In Postgres, UUIDs are better.
-- But changing type on a likely-used column is risky.
-- However, since this is a first-run system, we should do it now.
-- Actually, let's keep it simple and just fix the names and missing columns first.

-- ============================================================================
-- BASELINE SOURCE: 20260823050000_populate_missing_profile_fields.sql
-- ============================================================================

﻿-- Migrated from database/migrations/006_populate_missing_profile_fields.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration 006: Populate missing profile fields for existing users
-- Added: 2026-04-15

-- Update existing users with missing username - set to email prefix
UPDATE auth_users
SET username = SPLIT_PART(email, '@', 1)
WHERE username IS NULL OR username = '';

-- Note: full_name is left as NULL for existing users since we don't have
-- good defaults. Frontend will handle empty full_name gracefully.

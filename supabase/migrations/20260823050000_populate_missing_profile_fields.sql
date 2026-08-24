-- Migrated from database/migrations/006_populate_missing_profile_fields.sql (preserving original lineage)
-- Part of DATA-CONVERGE-2: Supabase data spine authority

-- Migration 006: Populate missing profile fields for existing users
-- Added: 2026-04-15

-- Update existing users with missing username - set to email prefix
UPDATE auth_users
SET username = SPLIT_PART(email, '@', 1)
WHERE username IS NULL OR username = '';

-- Note: full_name is left as NULL for existing users since we don't have
-- good defaults. Frontend will handle empty full_name gracefully.
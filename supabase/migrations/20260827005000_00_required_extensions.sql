-- AI KAREN production baseline prerequisite.
--
-- Schema authority: supabase/migrations
-- Purpose: make a fresh PostgreSQL + pgvector installation self-describing.
-- The application must never create database extensions at runtime.

CREATE EXTENSION IF NOT EXISTS vector;

COMMENT ON EXTENSION vector IS
    'Required by AI KAREN canonical memory embedding columns declared by production migrations.';

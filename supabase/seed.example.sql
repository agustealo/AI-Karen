-- Seed example for Supabase preview environments
-- Use synthetic fixture data only. Never clone production user data.

INSERT INTO tenants (id, name, plan, created_at) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Acme Corp', 'enterprise', now()),
  ('00000000-0000-0000-0000-000000000002', 'Globex', 'standard', now());

INSERT INTO users (id, tenant_id, email, name, created_at) VALUES
  ('00000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'alice@example.com', 'Alice', now()),
  ('00000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000001', 'bob@example.com', 'Bob', now());

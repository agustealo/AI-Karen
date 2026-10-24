-- Persona tables contain tenant-owned configuration and private interactions.
-- Enforce tenant context at the database boundary, not only in API WHERE clauses.
BEGIN;

DO $$
DECLARE target_table text;
BEGIN
  FOREACH target_table IN ARRAY ARRAY[
    'custom_personas', 'user_persona_preferences', 'persona_memory_entries'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target_table);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', target_table);
    EXECUTE format('DROP POLICY IF EXISTS persona_tenant_isolation ON public.%I', target_table);
    EXECUTE format(
      'CREATE POLICY persona_tenant_isolation ON public.%I FOR ALL '
      || 'USING (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), '''')) '
      || 'WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant_id'', true), ''''))',
      target_table
    );
  END LOOP;
END $$;

COMMIT;

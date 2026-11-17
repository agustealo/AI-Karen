-- KPLUG-CONV-02C3A: accommodate the pre-existing verified_committed
-- terminal state. The C2 schema already constrained the allowed values, but
-- its varchar(16) length blocked this 18-character status at PostgreSQL.
-- Never reinterpret a prepared/unknown claim as committed during migration.
BEGIN;

ALTER TABLE public.extension_lifecycle_operations
    ALTER COLUMN status TYPE varchar(24);

COMMENT ON COLUMN public.extension_lifecycle_operations.status IS
    'Lifecycle claim status: prepared is not executed; unknown stays frozen; verified_committed requires kernel observation and atomic global CAS.';

COMMIT;

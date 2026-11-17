-- KPLUG-CONV-02C3B2A: durable one-shot kernel execution admission.
-- A prepared claim is not physical execution. Once in_flight, a crash,
-- cancellation, or disconnected host cannot reuse the claim for a blind retry.
-- No consumer or API execution capability is introduced by this migration.
BEGIN;

ALTER TABLE public.extension_lifecycle_operations
    ADD COLUMN execution_started_at timestamptz;

ALTER TABLE public.extension_lifecycle_operations
    DROP CONSTRAINT extension_lifecycle_operation_status_check;

ALTER TABLE public.extension_lifecycle_operations
    ADD CONSTRAINT extension_lifecycle_operation_status_check
    CHECK (status IN (
        'prepared', 'in_flight', 'unknown', 'verified_committed', 'rejected'
    ));

ALTER TABLE public.extension_lifecycle_operations
    ADD CONSTRAINT extension_lifecycle_execution_started_check
    CHECK (
        status <> 'in_flight' OR execution_started_at IS NOT NULL
    );

-- Existing verified receipts predate one-shot execution admission. The
-- constraint requires timestamps only on NEW in_flight rows; historical
-- verified_committed rows are preserved without invented timestamps.

COMMENT ON COLUMN public.extension_lifecycle_operations.execution_started_at IS
    'Durable admission instant. in_flight is one-way and must not be retried after crash.';

COMMENT ON COLUMN public.extension_lifecycle_operations.status IS
    'prepared is not executed; in_flight may have produced a physical effect and cannot be re-entered; unknown stays frozen; verified_committed requires kernel observation and CAS.';

COMMIT;

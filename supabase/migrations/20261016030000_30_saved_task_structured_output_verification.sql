-- MI-11: optional creator-defined machine output conformance contract.
-- Existing automation_tasks stays the only saved-task definition authority.
BEGIN;
ALTER TABLE public.automation_tasks
    ADD COLUMN IF NOT EXISTS verification_contract jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.automation_tasks
    ADD CONSTRAINT automation_tasks_verification_contract_object_check
    CHECK (jsonb_typeof(verification_contract) = 'object');

COMMENT ON COLUMN public.automation_tasks.verification_contract IS
    'Optional versioned schema for deterministic ChatRuntime structured output checks; never independent goal completion proof.';

-- A declared output contract cannot be human-approved if the runtime checker
-- reported anything but "passed". This guard is atomic with MI-10 review CAS.
ALTER TABLE public.automation_tasks
    ADD CONSTRAINT automation_tasks_verified_machine_contract_check
    CHECK (
        status <> 'Success'
        OR verification_contract = '{}'::jsonb
        OR result_receipt #>> '{machine_verification,status}' = 'passed'
    );
COMMIT;

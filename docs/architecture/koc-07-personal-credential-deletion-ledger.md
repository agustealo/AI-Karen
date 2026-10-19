# KOC-07: Personal channel credential deletion request ledger

Status: **durable request intent only**. Managed WhatsApp remains disabled.

## Ownership

The existing `SqlChannelRepository` exclusively owns persistence. Migration 35
creates a tenant-RLS deletion ledger, with a foreign key to the operator-assigned
connection owner and parent connection. A repository transaction locks the
connection, verifies the current owner and revision, and inserts one
idempotent request. Reusing a key with a different user, session, or credential
scope is rejected.

`requested` is the only state this increment can issue. The schema reserves
explicit `provider_pending`, `provider_claimed`, `verification_pending`,
`verified`, and `unknown` states for future **separately governed**
transitions. The presence of a record is not a vendor operation, unlink
acknowledgement, or independently verified credential erasure.

No API route, vendor call, retry worker, fake QR, provider selection, or
UI success state was introduced. No credentials, raw QR, or personal message
contents are stored.

## Acceptance to continue

Next increments must bind a genuine authenticated provider response to the
request ID, add guarded state transitions with receipt evidence, preserve
audit and RBAC, implement bounded retry leases, and supply disposable
PostgreSQL concurrency/RLS proof. No public deletion action is authorized
until ChannelHost orchestrates a RuntimePolicy-approved request.

## Proof

`pytest -q tests/extensions/test_personal_credential_deletion_ledger.py`

`CHANNEL_TEST_DATABASE_URL=<disposable database> pytest -q tests/integration/test_channel_claim_concurrency_postgres.py`

Migration 35 requires PostgreSQL with the existing channel schema. Native
vendor behavior and independent erasure verification remain unproven.

# KOC-06: Managed credential deletion evidence

Status: **contract-only, default off, no vetted provider**.

KOC-05's remote unlink acknowledgement attests only that an approved
provider claims a device session was unlinked. This KOC-06 increment adds
a distinct `PersonalCredentialErasureReceipt`, scoped to connection revision,
provider-issued session, an operator/host-issued deletion request ID,
credential scope and vendor receipt. The canonical host evidence validator
rejects stale, future, mismatched, ambiguous, or whitespace-only claims.

This deliberately makes **no claim of independent verification**. Signing
or authenticating a provider response establishes origin, not completeness
of deletion across vendor databases, backups, logging systems or subprocessors.
Credential shredding and data retention remain security/compliance review
gates. A future vetted provider adapter must obtain native evidence using
verified APIs and authenticated responses, without making up receipt IDs.

No deletion endpoint, provider adapter, secret access, QR flow, activation,
UI success banner, or new orchestration service is introduced.

## Proof

`pytest -q tests/extensions/test_managed_credential_erasure_evidence.py tests/extensions/test_personal_transport_evidence.py tests/extensions/test_managed_personal_transport_contract.py`

Activation still requires documented vendor approval, tenant/owner/consent
checks, current RuntimePolicy permission, Vault-backed native authentication,
durable idempotent deletion request ownership, provider unlink evidence,
credential erasure acceptance, audit trails and genuine end-to-end proof.

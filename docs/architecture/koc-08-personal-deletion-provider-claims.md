# KOC-08: Vendor credential-erasure claims

Status: **internal persistence contract only**. No vendor approved or enabled.

`SqlChannelRepository.record_personal_credential_deletion_claim` can record
`provider_claimed` only after the caller supplies a typed
`PersonalCredentialErasureReceipt`. The trusted ChannelHost integration must
independently authenticate native vendor messages, validate their freshness
through `validate_credential_erasure_claim`, and govern RBAC/audit.
**This method is not an external ingress or sufficient vendor authentication.**

The repository locks the connection and request, checks the durable owner,
connection revision, provider, session, credential scope and host-issued
deletion request UUID. Only `requested` or `provider_pending` can advance to
`provider_claimed`; conflicting duplicate receipts are rejected. It never
produces `verified`, a success banner, or a user-facing deletion claim.

Next: wire a vetted provider adapter to canonical ChannelHost, add
native authentication and receipt freshness, explicit audit and independently
verified credential-erasure transitions, retry leases, and disposable PostgreSQL
race/RLS tests. No QR route, fake transport, extra orchestrator or distribution
build is authorized.

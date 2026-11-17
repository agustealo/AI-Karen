# KWA-01C6C2C1: operator-observed WhatsApp trial lineage

## Purpose

A real provider acceptance trial must connect an authenticated user's
sender identity to one **specific provider-originated message**, the host's
durable inbox, the canonical ChatRuntime reply, the host outbox and Meta
delivery/read status observations. It must not confuse one of those with
another or silently promote local SQL history to external certification.

The canonical owner remains `SqlChannelRepository`. This slice adds
**read-only inspection** of its existing tenant-scoped RLS tables. There are
no new status stores, transport hooks, provider adapters, public dashboards
or alternate model paths.

## Operator workflow

1. On an approved revision-pinned HTTPS deployment, use an authenticated,
   verified tenant administrator with `channel.inspect` capability.
2. Using an approved real Meta sandbox WhatsApp number, complete the
   one-time self-link command against the enabled scoped business number.
   That step must be independently observed as a real Meta-signed POST,
   never a locally signed fixture.
3. Send a **separate ordinary WhatsApp text** from that sender and retain
   its real Meta inbound ID, which normally starts `wamid.`.
4. Under **Admin → WhatsApp Cloud**, use the existing tenant connection card's
   **Inspect a real message trial** panel, or submit:

   ```text
   POST /api/channels/operator/whatsapp/connections/{connection_uuid}/trial-evidence
   Content-Type: application/json

   {"external_event_id":"wamid.<actual-provider-inbound-message-id>"}
   ```

   The inbound ID is deliberately carried in an authenticated JSON body,
   not a URL or query string. The response has `Cache-Control: no-store, private`.
   The API acquires a new, signed-in principal's `channel.inspect` decision
   from the canonical RuntimePolicy/RBAC path. The host checks the installed
   canonical WhatsApp adapter, then delegates to the existing repository.

5. Inspect the returned original connection revision, inbox status, active
   binding status, correlation ID, outbound status, SHA-256 fingerprint of the
   recorded outbound provider message ID, and **revision/recipient-matched**
   provider status states. No phone number, account ID, Vault handle, text,
   native signed bytes, raw provider message ID, user ID or challenge secret
   is projected.
6. Separately compare the outbound fingerprint against the SHA-256 of the
   **actual Meta Graph send response ID**, and compare the delivered/read
   status states with the real callback and provider-side sender observations.
   Capture evidence only in the operator's approved secure evidence system.

## Evidence interpretation

- `inbox_status=completed` **with a staged outbox row** reflects the
  existing ChatRuntime completion-and-stage transaction; pending,
  processing or failed inbox status does not prove an AI reply.
- `outbound_status=accepted` is only a host-staged reply; `sent` is a
  provider send-API receipt, **not** subscriber delivery.
- `provider_receipt_states` contains only exact
  tenant/connection/original-revision/provider-ID/recipient matches from
  the signed-status ledger. `delivered` and `read` remain
  recorded observations, not independent subscriber-side proof.
- `binding_currently_active` is current local binding state, not
  historical provider origin.
- A connection can be disabled or its revision advanced after the trial;
  the original message revision remains the ledger attribution scope.
- Missing events are **404**, authorization failures **403**, malformed
  requests **422**; SQL inconsistencies or source outages return **503**
  rather than an invented empty/success response.
- Every response explicitly states:
  `evidence_basis=host_persisted_lineage_only`,
  `meta_origin_independently_verified=false`, and
  `consumer_certified=false`.

A signed webhook produced by a local fixture can populate the same
ledger tables. Therefore **this endpoint cannot certify real Meta origin,
subscription configuration, independently delivered/read state, or full
consumer readiness without separate approved provider-side observation**.
All such claims must be documented outside this read-only projection.

## Tests

```bash
pytest -q tests/extensions/test_whatsapp_trial_evidence.py \
  tests/extensions/test_whatsapp_operator_api.py \
  tests/extensions/test_channel_admission_repository.py \
  tests/extensions/test_channel_delivery_repository.py

cd src/ui_launchers/Karen-AI-Theme
npx vitest run tests/settings/whatsapp-cloud-trial-evidence.test.tsx
npm run typecheck
npm run build
```

The dedicated disposable real PostgreSQL test also covers the exact
tenant/connection/identity/revision/receipt joins through
`tests/integration/test_channel_claim_concurrency_postgres.py` with
`CHANNEL_TEST_DATABASE_URL` pointing **only** to
`karen_channel_test`. The fixture is not a real provider acceptance
event and never grants consumer certification.

This slice follows the installed authority model: thin API ingress,
host policy and plugin gating, SQL truth, no UI-owned fallbacks and no
new execution path.

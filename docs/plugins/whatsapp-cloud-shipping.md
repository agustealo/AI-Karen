# WhatsApp Cloud API: installation, registration, and ship readiness

Status: **candidate, not a live WhatsApp connection**. Canonical plugin: `src/ai_karen_engine/extensions/plugins/whatsapp-cloud`. The generic extension executor is deliberately disabled for communication-channel manifests.

## Ownership and the UI status

- `PluginKernel` discovers and validates the pre-installed manifest. It does not grant tenant communication permissions.
- `ExtensionCoreManager` projects `capabilities.communication_channel=true` and `provides_ui=false` directly from that manifest.
- **Plugins & Tools Overview** must show “Frontend: not required (backend-only)” for this adapter, not “UI installed but not registered”. The “Retry Registration”, generic “Enable/Disable”, and “Remove UI” controls are inapplicable.
- `ChannelHostServices` is the sole live process owner for an installed transport. Its disabled-by-default settings and `ChannelActivationService` separately govern each tenant connection with existing RuntimePolicy, RBAC, and SQL revision checks.
- `CredentialVaultService` is the sole secret owner. The transport receives only a host-injected `ChannelVaultSecretResolver`; native event bodies cannot select an installation, tenant, user, credential handle, or provider.
- `ChannelIngressService` verifies signed raw POST content, normalizes text-only inbound events, and commits inbox records before returning 202; the shared worker handles ChatRuntime turns and durable outbox dispatch.
- API routes remain thin. Cloud API receipts confirming **sent** are not the same as delivery/read receipts.

## KWA-01C first slice: Meta phone identity preflight

Before the host's `ChannelActivationService` can commit a WhatsApp connection's
enabled revision, the existing adapter now makes a **read-only**, host-client
`GET /{phone_number_id}?fields=id,display_phone_number` against the configured
Graph version. The bearer token comes only from `ChannelVaultSecretResolver`.
A non-200 response, malformed metadata, missing display number, wrong returned
ID, timeout, or unavailable host HTTP GET denies activation without leaking
provider error details. No generic plugin enable or new credential store exists.

This attests that **the token can read the configured phone-number identity at
activation time only**. It does not establish that a phone is registered for
messaging, the WABA is subscribed to the correct webhook, inbound/outbound
traffic works, tokens remain valid, 24-hour service windows are enforced, or
a live Meta test-number trial passed. Those are independent release gates.

## KWA-01C2: host-enforced 24-hour customer service window (source only)

WhatsApp free-form reply dispatch now requires a **signed native customer-message
timestamp** stored in the existing tenant-FORCE-RLS `channel_inbox`. Migration
`56_whatsapp_customer_window_evidence` adds immutable `provider_event_at`.
Meta inbound text with a missing/malformed timestamp is rejected; legacy inbox
rows with no evidence do not authorize an outgoing send. Event identity digests
now include available native provider time, without changing legacy digests for
other channels.

After a one-shot outbox claim, `ChannelDeliveryService` checks the **PostgreSQL
clock** and verifies that a customer message in the past 24 hours belongs to the
exact tenant, connection revision, bound Karen principal, sender, destination,
and conversation. A second customer message can refresh the window, while
outgoing sends never do. The host reserves 65 seconds for the bounded network
call and refuses dispatch near expiry or when evidence is missing. Denials are
durably marked `whatsapp_customer_window_closed` without contacting Meta.
This guard never grants template messaging or initiates conversations.

**Acceptance limits:** This is source-level policy enforcement, not proof that
Meta will accept the message. Live provider clock skew, network latency,
policy changes, restart/recovery, and Meta test-number behavior need
independent acceptance. Existing queued replies tied to pre-migration inbox
records intentionally fail closed. Do not bypass this guard by calling an
adapter directly or enabling generic plugin execution.

## Operator setup (explicit opt-in)

1. Install/validate the preinstalled `whatsapp-cloud` manifest using Karen's governed plugin catalog. Do **not** use generic plugin `/load` to enable messaging.
2. Provision an approved Meta WhatsApp Business account, phone-number ID, app token, and app secret. Resolve the WhatsApp app's current supported Graph version from approved provider configuration, not arbitrary client input.
3. Supply tenant-scoped audited Vault secret types `access_token`, `app_secret`, `phone_number_id`, `graph_api_version`, and `webhook_verify_token`. No secrets should appear in Git, manifests, environment dumps, browser storage, or API responses.
4. The operator must explicitly set `KAREN_CHANNEL_HOST_ENABLED=true`, `KAREN_CHANNEL_SERVICE_PRINCIPAL_ID` to the trusted host actor, and `KAREN_CHANNEL_HOST_INSTALLATIONS_JSON` to a JSON mapping with `whatsapp-cloud` and **all five** required secret-type names. `KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON` is **not** applicable to Meta Cloud API.
5. Through the existing `ChannelActivationService`, provision an owner-bound, tenant-scoped connection whose `provider_account_id` matches the Vault `phone_number_id`, and explicitly activate it under a fresh `channel.activate` RuntimePolicy grant. An installed manifest alone does not create a connection.
6. Configure Meta's HTTPS callback to `/api/channels/webhooks/{tenant_uuid}/{connection_uuid}` with the same `webhook_verify_token`. The GET `hub.mode=subscribe&hub.verify_token=...&hub.challenge=...` route returns exactly the numeric challenge only after the host validates the tenant connection, canonical adapter, and Vault secret. Incorrect or missing configuration fails closed. **Do not log query tokens.**
7. Subscribe the WABA/app `messages` webhook field and configure a live Meta test account. POST events must have Meta's valid `X-Hub-Signature-256` over raw body bytes. Validate provider account, inbound identity binding, dedupe, and a fully authorized ChatRuntime round-trip in a real tenant.

These are operator requirements, **not an assertion that the current deployment is provisioned**.

## Not yet proven: release-blocking requirements

- [ ] Authenticated operator provisioning and activation through a usable admin connection flow, with Vault credential rotation and refusal on missing RBAC, tenant, or consent
- [ ] End-to-end Meta test-number handshake on a public HTTPS callback, signed inbound delivery, tenant identity linking, durable one-turn response, and provider-observed receipt
- [x] **Source-only:** Signed status batches and durable, monotonic PostgreSQL reconciliation are implemented by KWA-01B. This does **not** establish live Meta delivery/read evidence.
- [ ] **Provider acceptance:** Real Meta status batches, delayed/duplicate provider receipts, deactivation handling, and unmatched-status retention must pass end-to-end.
- [x] **Source-only:** Host-gated 24-hour free-form reply window using immutable signed inbound time and a claim-bound PostgreSQL clock check (KWA-01C2).
- [ ] **Provider acceptance:** Independently verify the 24-hour behavior against live Meta and establish explicit template/opt-in policy before any outbound initiation; no unrestricted templates or campaigns
- [ ] Network timeouts, retries, rate limiting, unknown-send semantics, exact-account fencing, rotation and revocation, audit/telemetry, provider downtime and incident recovery acceptance
- [ ] Real signed-in admin browser walkthrough at narrow and wide viewports, plus disconnection, replay, concurrency and privacy behavior
- [ ] Exact-head CI (Plugin Backend, Frontend, Security, Main Quality, First-Boot), postmerge main, and an independently attested live Meta sandbox trial

## Free-plugin release mirror

`src/ai_karen_engine/extensions/plugins/whatsapp-cloud` is the **pre-installed canonical source**. `free_plugins/essential/whatsapp-cloud` is intentionally **not published while these gates are open**. `free_plugins` is storage/distribution, never a registry, automatic installer or runtime alternate source.

When an adapter passes the ship gate, copy the **exact reviewed source files** and manifest into `free_plugins/essential/<id>`, record a provenance/CI evidence receipt, verify source/free tree content parity and package installation through the governed UI, and publish only after checks pass. Subsequent source changes invalidate the mirrored release until the parity/release check is repeated.

For existing shipped essentials, any divergence between a preinstalled source and a free copy is **release drift** to audit and reconcile, not a reason to choose the free directory as runtime authority.

## KWA-01C3: signed status-only receipts after channel deactivation

A Meta callback can arrive after an operator disables a tenant WhatsApp
connection. The canonical host now has a **separate, receive-only** path for
that case. When the persisted connection is disabled, the installed WhatsApp
adapter verifies `X-Hub-Signature-256` against host-injected Vault credentials
and parses the same bounded native batch contract. Only a *nonempty, pure
status batch* is eligible. Mixed inbound texts, link commands, unknown native
changes, missing/invalid signatures, and callbacks for other channel types
are rejected before any persistence or ChatRuntime work.

`SqlChannelRepository` accepts a delayed status **only** when the same
tenant/connection already has a finalized, provider-identified outbox send
with the exact recipient and original inbox revision. The SQL checks
`enabled=false` and the observed connection revision again, derives the
historical revision from the existing send, and refuses unknown statuses
rather than inventing old deliveries. The shared monotonic reconciler
permits `sent → delivered → read` without downgrades, while leaving the
connection disabled. Signature replay stays digest-idempotent. If a status was
committed *before* a send finished but the channel was disabled before the
send's provider receipt finalized, the existing outbox finalizer also
reconciles that pending status against the original inbox revision and
current disabled revision fence. No provider call, worker submission, new
message or user identity binding is possible from the disabled path.

**Limitations:** This is source proof, not live Meta callback acceptance.
Unmatched historical IDs are ignored, not silently promoted; their
retention/incident policy remains a separate release gate. Credential
rotation may make old callbacks unverifiable and those are correctly
denied. New connections are never activated by status-only callbacks.
External provider subscription removal, personal unlink, and credential
erasure are neither performed nor claimed. The canonical plugin stays
unpublished in `free_plugins/essential` until live Meta, migration, browser
and exact-head gates pass.

## KWA-01B source implementation: signed batches and durable status evidence

The canonical WhatsApp adapter now normalizes multiple signed \`entry[].changes[]\`,
\`messages[]\`, and \`statuses[]\` into one bounded typed transport batch. The
existing \`ChannelIngressService\` verifies one raw native signature and checks
installation, tenant, connection revision and capabilities before processing.
Only text events reach the durable inbox. Unsupported media/event types are
counted and ignored, never converted to prompts; malformed or cross-phone
payloads are denied. A \`/link\` proof cannot share a batch with another event.

Migration \`54_channel_provider_status_ledger\` adds a tenant-FORCE-RLS status
evidence ledger, keyed by an adapter-derived idempotency digest of Meta's
signed message ID, recipient, state and timestamp. Meta does **not** supply a
globally unique status event ID; the hash is an internal deduplication key,
not a native ID or an alternative signature. Signed statuses contain no Karen
user identity and do not execute ChatRuntime, user plugins, or sends.

The canonical SQL repository stages status-before-send observations, then
checks matching tenant + connection + current revision + original inbox
revision + provider message ID + recipient before advancing a finalized
outbox. It never changes \`accepted\` into success. Once a verified provider
send is finalized, pending signed receipts may advance \`sent\` to \`delivered\`
or \`read\`. Out-of-order \`sent\` and contradictory lower-confidence
\`failed\` observations cannot reduce \`read\`. A terminal \`failed\` row is
not reopened. The unique scoped provider-message index fails a migration
rather than allowing ambiguous attribution. A POST webhook returns 202 only
after every supported event is committed; partial failures are retried safely
through unique inbox IDs and status receipt digests. An HTTP 202 is only
**durable admission**, never proof of ChatRuntime success or provider delivery.

**Still blocked:** production data migration rollout and review of existing
duplicate provider message IDs; a governed retention/cleanup policy for
unmatched status receipts; live Meta acceptance for status events received after connection
deactivation; real Meta test-number signature interop, delayed read/failure
events, and live signed-in end-to-end acceptance. All remain required before
shipping the canonical source to the \`free_plugins\` release mirror. Do
not infer real provider status from source tests alone.

Proof in existing plugin gates:
\`pytest -q tests/extensions/test_whatsapp_cloud_transport.py
tests/extensions/test_channel_ingress_service.py
tests/extensions/test_channel_delivery_repository.py
tests/integration/test_channel_claim_concurrency_postgres.py\`.

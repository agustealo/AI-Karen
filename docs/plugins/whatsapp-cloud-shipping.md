# WhatsApp Cloud API: installation, registration, and ship readiness

Status: **candidate, not a live WhatsApp connection**. Canonical plugin: `src/ai_karen_engine/extensions/plugins/whatsapp-cloud`. The generic extension executor is deliberately disabled for communication-channel manifests.

## Ownership and the UI status

- `PluginKernel` discovers and validates the pre-installed manifest. It does not grant tenant communication permissions.
- `ExtensionCoreManager` projects `capabilities.communication_channel=true` and `provides_ui=false` directly from that manifest.
- **Plugins & Tools Overview** must show “Frontend: not required (backend-only)” for this adapter, not “UI installed but not registered”. The “Retry Registration”, generic “Enable/Disable”, and “Remove UI” controls are inapplicable.
- `ChannelHostServices` is the sole live process owner for an installed transport. Its disabled-by-default settings and `ChannelActivationService` separately govern each tenant connection with existing RuntimePolicy, RBAC, and SQL revision checks.
- `CredentialVaultService` is the sole secret owner. The transport receives only a host-injected `ChannelVaultSecretResolver`; native event bodies cannot select an installation, tenant, user, credential handle, or provider.
- `ChannelIngressService` verifies signed raw POST content, normalizes text-only inbound events, and commits inbox records before returning 200; the shared worker handles ChatRuntime turns and durable outbox dispatch.
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

## KWA-01C4: governed unmatched-status evidence retention (source only)

The host does **not** run automatic status cleanup on startup or webhook
admission. Database migration 57 adds `channel_provider_status_tombstones`, a
tenant-FORCE-RLS, digest-only anti-replay ledger. Tombstones retain no phone
numbers, original Meta message IDs, raw webhook payloads, user IDs or Vault
credentials. A database trigger prevents later mutation of their evidence.

An authenticated operator must explicitly enable
`KAREN_CHANNEL_STATUS_RETENTION_ENABLED=true` and possess the independent
`channel.status_prune` RBAC/RuntimePolicy capability for the installed
`whatsapp-cloud` connection. Default configuration disables deletion. The
centrally validated `KAREN_CHANNEL_STATUS_RETENTION_DAYS` defaults to **90**
(allowed 30..3650); the `KAREN_CHANNEL_STATUS_RETENTION_BATCH_LIMIT` defaults
to **100** (allowed 1..1000). These values are host settings, never native
callback or browser-controlled policy parameters.

The authenticated `POST /api/channels/{connection_uuid}/status-retention`
accepts only a strict `dry_run` boolean and an explicit `confirm_prune=true`
when `dry_run=false`. Actor and tenant derive from session authentication;
the route obtains a fresh authorized plan, and the canonical host verifies
eligibility again before calling the existing SQL repository. A dry run reports
the bounded number of eligible receipts without mutation.

Pruning targets only statuses older than the database-clock retention cutoff,
inside the exact tenant/connection/current revision, with no matching
provider-message ID and recipient in a durable outbox. The SQL excludes live
outbound claims, locks both candidate receipt and connection rows with
`SKIP LOCKED`, creates SHA-256 digest-only tombstones in the same transaction
and deletes only rows successfully tombstoned. **Matched delivery/read evidence
is never a pruning candidate.** A signed callback replay matching a tombstone
is acknowledged without recreating deleted personal data; a conflicting
digest is rejected. The host logs counts, revision and policy decision ID,
not the provider message, phone or credential.

**Acceptance remains open:** Exact-head PostgreSQL/CI proof, deployed operator
flow, real Meta provider acceptance, legally configured retention obligations
and adversarial concurrent replay/cleanup tests are independent of source-level
implementation. Do not enable destructive cleanup in production without those
checks. Do not ship WhatsApp to `free_plugins/essential` prematurely.

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
- [x] **Source-only:** Explicit RBAC/RuntimePolicy-gated unmatched-status retention, tenant-locked bounded cleanup and digest tombstones (KWA-01C4).
- [ ] **Provider acceptance:** Real Meta status batches, delayed/duplicate provider receipts, deactivation handling, and production retention obligations must pass end-to-end.
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
rather than allowing ambiguous attribution. A POST webhook returns 200 only
after every supported event is committed; partial failures are retried safely
through unique inbox IDs and status receipt digests. An HTTP 200 is only
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



## KWA-01C5B: manifest-governed native payload budget

`capabilities.communication_channel.max_native_body_bytes` is a strict, versioned
per-transport declaration. The currently installed WhatsApp and Telegram
manifests both declare **65,536 bytes**. The shared channel host retains its
operator-configured upper bound, but may not override a lower approved
transport budget. Active and disabled-status-only webhook paths check this
declaration before adapter signature normalization. Over-budget requests
return HTTP **413** rather than being mislabeled as forged signatures; no
inbox, status event, ChatRuntime execution or provider dispatch occurs.

This is a **source-contract correctness change, not a capacity increase**.
Meta documents WhatsApp payload envelopes up to approximately **3 MB** and
general Graph webhook aggregation up to **1,000** updates. Karen still
supports only 64 KiB and 100 counted events. Do not raise those ceilings
until the canonical repository has measured, bounded bulk admission and
durable retry behavior for the largest supported valid signed batch.


## KWA-01C5C1: atomic bounded status-batch persistence

The canonical `SqlChannelRepository` now accepts one verified 1..100-receipt
status batch inside a **single tenant-RLS transaction and a single scoped
replay/prune advisory lock**. Both the individual-receipt and batch entrypoints
reuse the same insert, exact digest/tombstone replay, current-connection
revision, recipient binding and monotonic reconciliation SQL.

The host's `ChannelIngressService` delegates provider status tuples to that
canonical repository method after native signature and batch authorization.
If any receipt fails validation, collides with different evidence, loses its
connection revision, or encounters a database failure, the entire status batch
transaction rolls back and the webhook receives no success acknowledgement.
Exact signed retries converge without duplicate status records or chat turns.

Mixed inbound messages still use their own durable inbox admission path.
Deactivated WhatsApp receipts retain their restricted historical pathway.
This is **not** a 3 MB / 1,000-event capacity increase, does not measure
provider-facing p95/p99 latency, and does not establish live Meta connectivity.


## KWA-01C5C2: reproducible disposable PostgreSQL latency evidence

The Plugin Backend workflow now runs
`tests/integration/test_channel_status_batch_benchmark_postgres.py`
**after** the canonical disposable `karen_channel_test` integration proof.
It benchmarks the actual `SqlChannelRepository` per-receipt versus batch
commit/replay paths for 1, 10, 25 and 100 authenticated normalized status
events, using fresh IDs and a dedicated throwaway tenant. All operations
enforce real PostgreSQL RLS-scoped transactions; no provider credentials,
network callbacks or live tenant records are involved.

An attached `channel-status-postgres-benchmark` CI artifact records
individual sample durations, p50/p95/p99 descriptive sample quantiles,
transaction counts per operation, PostgreSQL/Python versions and checked-out
source SHA. The default CI probe uses six repetitions and explicitly marks
percentiles as **exploratory**, not p99 service-level evidence. For a deeper
local run, set `KAREN_CHANNEL_STATUS_BENCHMARK_REPETITIONS=100` in the
dedicated disposable test database after applying the checked-in migrations.

This **does not** increase the 64 KiB / 100-event admission contract, set
arbitrary timing thresholds, prove real Meta callback timeouts, measure
browser/API latency, or establish live WhatsApp connectivity. Latency
comparison and concurrency/retention contention evidence must inform a
separate governed release decision before the capacity ceiling can change.


## KWA-01C5C3: concurrent bounded batch replay versus retention prune

The existing disposable PostgreSQL channel concurrency suite now creates an
isolated active WhatsApp connection and records **100 valid normalized status
receipts**. After aging only those unmatched test receipts, it races an
identical 100-receipt replay against the canonical destructive retention
prune. Both operations must finish through the existing shared advisory lock,
and the final result must contain zero PII-bearing status rows and exactly
100 digest-only tombstones.

Three more parallel exact batch replays must return successful durable replay
acknowledgements without restoring deleted metadata. Intentionally corrupting
one test-only tombstone digest must fail the whole batch closed, with zero
new status rows. No new plugin code, secret path, data store, migration, HTTP
endpoint or transport limit is added by this test.

This verifies PostgreSQL concurrency and archival idempotence under the
existing 64 KiB / 100-event contract, **not** callback throughput,
live Meta signature interoperability, provider latency SLOs or approval to
release the WhatsApp transport.


## KWA-01C6A: authenticated operator connection lifecycle

The canonical FastAPI router registry now exposes three authenticated,
tenant-scoped operator actions for the **preinstalled** `whatsapp-cloud` adapter:

- `POST /api/channels/operator/whatsapp/connections` accepts a Meta numeric
  phone-number ID and an opaque tenant Vault credential handle, not raw
  credentials. It mints a fresh `channel.provision` plan through
  `ChannelActivationService.issue_action_plan`, reuses the host's Vault
  reference authorizer, and persists a **disabled** revision-1 connection.
- `POST /api/channels/operator/whatsapp/connections/{connection_uuid}/activate`
  accepts only `expected_revision`. The host resolves the canonical installed
  adapter, verifies tenant/installation/revision, and delegates to the existing
  `ChannelActivationService.activate`. The transport must complete its
  read-only Meta Graph phone identity probe before the transaction can mark
  the connection enabled. A stale revision is not silently upgraded.
- `POST /api/channels/operator/whatsapp/connections/{connection_uuid}/deactivate`
  accepts only `expected_revision`. The existing service durably revokes the
  connection before asking the adapter to stop, retaining status-only evidence
  eligibility for previously finalized sends.

The API never accepts user IDs, tenant IDs, roles, signed policy plans,
adapter selection, Graph URLs, secrets or raw provider tokens from callers.
The signed-in user comes from the established session dependency;
`issue_action_plan` verifies live roles and RuntimePolicy, and
`ActionExecutionGate` remains in the existing lifecycle owner. Requests with
unknown fields, forged grant objects, stale revisions or mismatched tenant
identity fail closed, with redacted error responses.

Results expose the persisted connection revision and exact stage. Only a
successful activation may report `provider_phone_verified=true` because the
actual adapter probes Meta before the activation CAS. Every response keeps
`webhook_subscription_verified`, `signed_inbound_verified` and
`delivery_verified` false. These remain **separate, live provider acceptance
gates**. No provider test number, webhook or end-user chat is created by the
API itself; no new worker, installer, credential store or generic plugin
executor is introduced.

**Source proof:** `pytest -q tests/extensions/test_whatsapp_operator_api.py
tests/extensions/test_channel_activation_service.py` and the exact-head
Plugin Backend, Plugin Security Reports, Main Quality and relevant production
boot gates. A signed-in operator UI and actual Meta sandbox transcript are
still necessary for consumer-ready shipping.


## KWA-01C6B: bounded tenant operator inventory and Admin UI

Admin Settings → WhatsApp Cloud now offers an authenticated, operator-only
workflow using the same `ChannelActivationService` action plans and canonical
host authority as KWA-01C6A. Operators can provide a **numeric Meta phone-number
ID** and an **existing opaque Vault handle** to provision a disabled connection,
inspect the tenant's persisted connections, activate after the real Meta Graph
identity probe, or durably deactivate with an exact expected revision. The
frontend submits neither actor identity nor runtime policy grants.

`GET /api/channels/operator/whatsapp/connections` first mints a fresh
`channel.inspect` plan, then the host verifies the installed canonical
adapter and live operator entitlement before delegating to
`SqlChannelRepository.list_whatsapp_operator_connections`. The SQL executes
inside the existing tenant-scoped transaction/RLS boundary, filters
`installation_id='whatsapp-cloud'`, returns **only** UUID, persisted revision
and enabled flag, and refuses an inventory larger than 50 records. It never
selects Vault handles, token values or Meta phone identifiers. The UI rejects
malformed/unexpected response shapes, clears previous tenant state on identity
changes, and gives no fake empty or connected state when backend inspection
fails.

The UI text deliberately distinguishes **persisted Karen enablement** from
live Meta webhook health or message delivery. Successful activation may confirm
a Meta phone identity check, but never changes the displayed webhook,
signed-inbound or delivery indicators to verified. Failed or uncertain
mutations do not synthesize saved/connected state and require a fresh backend
read. No localStorage or browser credential persistence is added.

Dedicated proof includes
`pytest -q tests/extensions/test_whatsapp_operator_api.py`,
the disposable `tests/integration/test_channel_claim_concurrency_postgres.py`,
and frontend `tests/settings/whatsapp-cloud-settings.test.tsx`. Production
acceptance still needs a real signed-in browser walkthrough, a configured
Meta sandbox, public callback handshake, verified identity binding and
provider-observed signed delivery/read receipts. Source-only UI/API success
is **not** a WhatsApp shipping approval.


## KWA-01C6C1: canonical admin reachability and opt-in real-browser observer

The existing `WhatsAppCloudSettings` is now reachable through the authenticated
dashboard's administrator-only **Admin settings** link and Karen's canonical
`/admin` → **WhatsApp Cloud** tab, not only from a
`SettingsDialog(adminMode=true)` configuration that the consumer dashboard
does not use. This mounts the already governed component and its authenticated
operator endpoints; it adds no second API, provider selector, credential owner,
installation path, policy grant, or lifecycle implementation.

`tests/settings/whatsapp-cloud-admin-navigation.test.tsx` guards the actual
admin tab integration in the ordinary frontend test suite. The read-only
`e2e/whatsapp-cloud-admin-acceptance.spec.ts` is separately **opt-in** for an
approved HTTPS deployment with a dedicated, authorized, sanitized operator.
The real browser tests exercise **390, 768 and 1440 px** widths, sign in through
Karen, follow the administrator navigation link into the actual admin tab,
and require an HTTP 200 for canonical
`channel.inspect` inventory. They reject unexpected inventory fields, ensure
the UI distinguishes locally enabled connections from provider health, and
verify that observing the screen issues no channel mutations. No route mocks
or synthetic connection state are used.

From `src/ui_launchers/Karen-AI-Theme` on an approved deployment, export
`KAREN_BASE_URL` (exact approved HTTPS origin),
`KAREN_WHATSAPP_DEPLOYMENT_REVISION` (exact reviewed 40-character SHA),
`KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` through the operator's secure
environment, then run:

```bash
KAREN_WHATSAPP_ADMIN_ACCEPTANCE_REQUIRED=true \
npx playwright test e2e/whatsapp-cloud-admin-acceptance.spec.ts \
  --config=e2e/playwright.config.ts --project=chromium --retries=0
```

The URL in this command denotes an operator-selected, authorized HTTPS
deployment, **not** an existing or verified installation. Keep actual secrets
outside source control and CI artifacts. This suite disables Playwright traces,
screenshots and video; the approved login helper refuses untrusted origins.
Without explicit opt-in it skips, and a skipped test is never a passing live
browser acceptance receipt. With opt-in, missing credentials, denied inventory,
unavailable host, unexpected backend fields, or unreachable admin navigation
fail the test.

**Not certified by this slice:** a real Meta webhook challenge response, Meta
subscription, signed native message, identity link, ChatRuntime turn, outbound
provider message ID or delivered/read receipt. Those require separately
reviewed, credential-governed provider-side evidence on the exact deployed
commit and cannot be inferred from this browser observation or green CI.


## KWA-01C6C2A: revision-fenced real HTTPS callback challenge

The opt-in `e2e/whatsapp-cloud-webhook-handshake.spec.ts` exercises Karen's
**actual public HTTPS** `GET /api/channels/webhooks/{tenant_id}/{connection_id}`
route with an operator-approved, already enabled tenant connection and its
existing Vault-managed `webhook_verify_token`. It creates no new callback,
Vault secret, channel state, runtime selection, test account, or provider
adapter.

Both live-browser suites now reuse
`e2e/fixtures/whatsapp-acceptance-deployment.ts`: the candidate must be a
clean HTTPS origin and its real `/api/deployment-revision` response must match
exactly the operator-reviewed commit SHA. Mismatches, redirects and missing
deployment proof stop acceptance. This is deployment identity checking against
the configured target, not independent binary attestation.

From `src/ui_launchers/Karen-AI-Theme`, export these using an approved
operator secret-injection mechanism (never place tokens in CLI arguments,
checked-in `.env` files, test reports or browser storage):

- `KAREN_BASE_URL`: reviewed deployed HTTPS origin, no path or query
- `KAREN_WHATSAPP_DEPLOYMENT_REVISION`: reviewed 40-character commit SHA
- `KAREN_WHATSAPP_ACCEPTANCE_TENANT_ID`: actual isolated tenant UUID
- `KAREN_WHATSAPP_ACCEPTANCE_CONNECTION_ID`: its **enabled** connection UUID
- `KAREN_WHATSAPP_ACCEPTANCE_VERIFY_TOKEN`: the real Vault-approved callback
  verification token associated with that connection

Then execute the explicit, isolated live probe:

```bash
KAREN_WHATSAPP_WEBHOOK_HANDSHAKE_REQUIRED=true \
npx playwright test e2e/whatsapp-cloud-webhook-handshake.spec.ts \
  --config=e2e/playwright.config.ts --project=chromium --retries=0
```

The test makes four **read-only, unauthenticated** requests to the approved
host: valid subscription returns HTTP 200 and the *exact numeric challenge*
with `Cache-Control: no-store`; a well-formed but changed token, a missing
token and an invalid mode must each return HTTP 403. Network errors are
redacted. Traces, screenshots, video and secret-bearing test attachments are
disabled; do not turn on verbose HTTP debug or request URL logging because
Meta's GET verification protocol necessarily places the verify token in the
query string. Refuse unknown or unreviewed public hosts.

**Evidence boundaries and mandatory follow-up:**

1. A green source CI or skipped opt-in test is **not** a live host proof. The
   opt-in test must run against the exact approved deployed SHA, producing a
   passing Playwright job on that deployment.
2. A successful operator-originated host GET is **not** a verified Meta
   subscription. Independently configure the HTTPS callback in Meta's
   WhatsApp test app, subscribe its `messages` field, and observe an actual
   provider-side verified subscription. Retain redacted provider confirmation
   metadata, never a raw token or unmasked phone identifier.
3. A Meta GET handshake is **not** signed inbound ChatRuntime success.
   Independently observe a real provider-originated POST authenticated by
   `X-Hub-Signature-256`, tenant/identity binding, durable inbox admission,
   one authorized ChatRuntime turn and a provider-identified outbound send.
4. A Meta API response saying `sent` is **not** delivered/read. Observe signed
   provider receipts and their bounded, monotonic PostgreSQL reconciliation,
   including replay, out-of-order and deactivation behavior.
5. Do not publish `free_plugins/essential/whatsapp-cloud` or claim consumer
   readiness until all operator, provider, RBAC, retention and recovery gates
   have independent exact-deployment evidence.

Never forge a Meta signature with a local test token and label that provider
acceptance. Source-only signed fixtures remain useful security regressions,
but do not substitute for provider traffic.

## KWA-01C6C2B1: authenticated self-link proof and live RBAC configuration

The active Meta inbound acceptance path requires a verified Karen identity
binding before normal WhatsApp text can enter ChatRuntime. The existing
`ChannelLinkService` and PostgreSQL `channel_link_challenges` already issue
256-bit one-time token digests and accept only signed, unexpired native
`/link` commands. Before this slice, that issuance service was not wired to
the active channel host or an authenticated API, and `channel.link` was
absent from the canonical channel action allowlist.

The central RBAC registry now defines `channel.link` for verified Karen
users. The checked-in effective role configuration also explicitly grants
admins the already implemented channel operator actions, which the old
checked-in admin map omitted. Regular users gain **only** `channel.link`,
not provision, activation, send, retention or inspection authority. The
`channel.link` exception to the manifest's operator-only role gate is
limited to fresh, tenant-scoped account self-linking: the normal RBAC
`Permission.CHANNEL_LINK`, RuntimePolicy, approved execution plan and
`ActionExecutionGate` still all apply.

The new authenticated endpoint:

```text
POST /api/channels/identity/whatsapp/connections/{connection_uuid}/challenge
```

takes no user-supplied identity, tenant, permission, provider account, secret,
sender or TTL. With a live verified session, the host verifies the installed
canonical WhatsApp adapter and the original link service verifies the enabled
tenant connection before issuing a short-lived, one-use `/link <token>`
command. Only the digest is persisted; the command is returned once with
`Cache-Control: no-store, private`. Follow the approved operator workflow to
send that command **from the actual WhatsApp test sender** to the configured
business test number. The inbound POST must be Meta-signed and bound to the
exact existing tenant connection to consume the challenge. Failed, used,
expired, foreign-tenant and revoked credentials never create a sender binding
or ChatRuntime message.

**Source proof:**

```bash
pytest -q tests/extensions/test_whatsapp_self_link_api.py \
  tests/extensions/test_channel_provision_and_link_service.py \
  tests/extensions/test_channel_verified_link_ingress.py \
  tests/extensions/test_whatsapp_operator_api.py \
  tests/extensions/test_channel_runtime_policy_permissions.py
```

These are source and policy regressions, **not** Meta sender or signed-inbound
certification. An approved, observed provider-originated signed `/link`
message, then a separate ordinary signed text with a durable Inbox →
ChatRuntime → outbox → provider-receipt chain are still necessary. The
one-time proof is a bearer credential: never publish or paste it into bug
reports, browser logs, screenshots, telemetry or CI.

The standalone issuance endpoint intentionally does not invent a linked
status in the UI; that must be derived from future bounded, tenant-scoped
backend evidence rather than optimistic client state.

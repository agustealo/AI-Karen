# Telegram Bot Channel: operational readiness and release gates

Status: **installed transport; not certified live**. The generic plugin runtime intentionally
keeps communication channel packages disabled. A communication installation is not an
independently mountable frontend plugin or an active tenant connection.

## Source of truth

| Responsibility | Existing canonical owner |
| --- | --- |
| Transport manifest and native Bot API protocol | `src/ai_karen_engine/extensions/plugins/telegram-bot/` |
| Installed channel eligibility | `PluginKernel.get_channel_activation_manifest` |
| Host dependency composition | `services/channels/host.py` |
| Host configuration | `config/channels.py` |
| Tenant activation/revision fencing | `services/channels/activation.py` |
| Native webhook authentication and identity linking | `services/channels/ingress.py` and `linking.py` |
| Identity Vault secrets and audited resolution | `services/identity_vault/credential_vault_service.py` |
| Durable inbox/outbox and RLS | `persistence/repositories/channel_repository.py` |
| Chat execution, policy and model selection | Canonical `ChatRuntime` and `RuntimePolicy` |
| Operator/frontend projection | `extensions/platform/core/manager.py`, `plugin_host/registry.tsx`, `PluginOverviewPage.tsx` |

## Interpreting Plugin Overview

The Telegram manifest declares `provides_ui=false` and a
`communication_channel.transport=telegram-bot`. The backend installation must
not be interpreted as a separately installed React UI package. The frontend
must display no embedded UI required and must not propose Retry Registration,
UI Unmounted, Remove UI, or generic Enable as the way to activate Telegram.

A backend lifecycle status of `disabled` is expected for the generic extension
registration. **It does not prove that any tenant connection is configured,
connected, or authorized.** Tenant connection health must come from the
Channel Gateway's persisted connection and host readiness evidence, not from a
local React component or a synthetic green status.

## Host activation requirements

Operator-controlled config uses `KAREN_CHANNEL_HOST_ENABLED`,
`KAREN_CHANNEL_HOST_INSTALLATIONS_JSON`, and
`KAREN_CHANNEL_SERVICE_PRINCIPAL_ID`. The Telegram installation must declare
the two required Vault types `bot_token` and `webhook_secret`; enabled host
configuration missing an installation or audit actor fails startup. The existing
`ChannelHostSettings.validate` owns validation and bounded transport budgets.

The operator must establish a real Telegram bot and register a public HTTPS
webhook that maps to Karen's governed
`POST /api/channels/webhooks/{tenant_id}/{connection_id}` endpoint, with Telegram's
`X-Telegram-Bot-Api-Secret-Token` matching the Vault-governed signing secret.
Neither manifest discovery nor backend host startup automatically registers
Telegram's remote webhook. Do not claim this occurred without provider evidence.

Provision a disabled, tenant-scoped channel connection with a canonical Vault
credential handle. A verified authenticated Karen principal must complete the
one-use native sender proof before ordinary Telegram text can reach ChatRuntime.
An authorized administrator must activate the connection through
`ChannelActivationService`, with fresh identity, RBAC, RuntimePolicy,
ActionExecutionGate and connection revision CAS. Persisted enabled state alone
must never auto-resume a native connection after a host restart.

Ingress accepts only authenticated private text events, bounded bodies and
untrusted Telegram update/sender IDs. It must never treat Telegram IDs as Karen
tenant/user identifiers. The durable inbox deduplicates update IDs and scopes
execution to the verified principal. Outbound is one-shot and fenced through
the canonical outbox; unknown provider responses/timeouts remain UNKNOWN and
are never blindly retried. Telegram `sendMessage` provides SENT evidence only
for HTTP 200, `ok:true`, a positive integer message ID, and exact integer
recipient chat ID; it does not provide delivered/read proof.

## Release acceptance

1. **Source contract:** manifest validates; catalog projects the channel type
   without secrets; transport-only UI displays N/A rather than false registration;
   generic plugin enable does not activate a channel.
2. **Security:** invalid webhook secret, external sender spoofing, cross-tenant
   connection, invalid /link proof, revoked Vault credential, expired credential,
   disabled host and rotated connection are denied.
3. **Durability:** real PostgreSQL tenant RLS, concurrent inbox/outbox claims,
   duplicate webhook, restart, ambiguous delivery and revocation tests pass.
4. **Runtime:** verified linked sender receives a response from the **existing**
   ChatRuntime with policy/RBAC and canonical conversation provenance.
5. **Real Telegram acceptance:** operator confirms TLS webhook registration,
   authenticated incoming message, ChatRuntime response, provider sendMessage
   receipt with matching recipient, and truthful error behavior under rejected,
   timed-out, restarted and revoked conditions. Record a correlation ID, exact
   deployed commit, tenant-safe audit evidence and native provider receipt ID.
6. **UI/browser:** authenticated operator views accurate installation/connection
   health, including absent host and missing connection; no false UI-install or
   activation success. Responsive/error-state acceptance must be observed.
7. **Release packaging:** only after all required gates pass, verify version,
   manifest, hashes and matching package content in the preinstalled and free
   distribution catalogs using their existing packaging owner. No duplicate
   runtime registry or active package copy in discovery paths.

CI/static tests cannot substitute for a real bot account and real network
acceptance. Until that evidence exists, report **source candidate**, not
consumer-ready or live connected.

## Source verification commands

Run the targeted native transport and channel contract tests before relying on
integration CI:

```bash
pytest -q tests/extensions/test_telegram_channel_transport.py tests/extensions/test_channel_catalog_ui_contract.py
pytest -q tests/extensions/test_channel_host_lifecycle.py tests/extensions/test_channel_secret_resolution.py
pytest -q tests/architecture/test_plugin_store_api_shape_guards.py
python -m compileall src
ruff check src tests
```

For live SQL/RLS contention acceptance, use the existing disposable, dedicated
channel test database and follow the configuration documented in
`tests/integration/test_channel_claim_concurrency_postgres.py`. Never aim this
test at a production tenant database.

Treat missing GitHub Actions results for a rewritten branch as missing
verification, even when the old PR head was green. Only exact-head results
authorize merging.

## Provider-side verification boundaries

An operator may inspect Telegram Bot API `getWebhookInfo` using the
configured bot identity, but provider response data must be treated as
untrusted until it is authenticated by the existing host transport. The
operator must compare the reported URL with the expected HTTPS channel
webhook endpoint and confirm that outstanding provider errors are not
silently ignored. Never capture the bot token, full webhook URL containing
sensitive routing identifiers, or native message body in routine telemetry.

The existence of a public HTTPS URL is not itself proof of a valid webhook:
native authentication, the correct tenant connection, a linked actor, a
durably accepted inbox event, a governed ChatRuntime invocation, and a
matching Telegram send receipt are separate acceptance observations.

## Read-only native webhook inspection

The installed Telegram adapter now has a host-internal `inspect_webhook`
operation. It asks Telegram's official `getWebhookInfo` endpoint only after
the exact tenant connection has been locally activated. The method does not
register, delete, modify or replay a webhook. The result deliberately includes
only `registered`, `path_matches`, `pending_update_count`,
`provider_reported_error`, and `endpoint_origin_verified=false`.

The path comparison is scoped to Karen's existing
`/api/channels/webhooks/{tenant_id}/{connection_id}` route. It is **not**
a full configured-origin check. Provider evidence may be historical and is not
proof of a successful signed incoming webhook. Never translate these fields to
"connected" or "healthy" without host-side configured-origin matching,
RBAC-authorized presentation and an observed end-to-end message round-trip.

Telegram's returned URL, IP and diagnostic text remain private; they are not
placed in plugin health reports or ordinary logs. A failed or malformed
inspection denies with a generic error. The canonical Channels host will need
a separately authorized, read-only projection before these results can appear
in consumer UI. This slice intentionally adds no public endpoint.

## Governed operator provisioning API

An authenticated and verified administrative actor may request a **disabled**
Telegram connection through the existing Channels ingress:

`POST /api/channels/personal/operator/telegram/connections`

The body contains only `provider_account_id` (the operator's nonsecret
account label) and `credential_handle` in canonical
`vault://<lowercase-UUID>` form. Do **not** put the Telegram Bot API token,
webhook signing secret, tenant, actor, permissions, or activation flags into
the request body. The referenced credential must already be stored in the
canonical Identity Vault with the Telegram installation's required secret
types and tenant access controls.

The route derives tenant and user from the authenticated Karen session, issues
a fresh `channel.provision` plan via the canonical activation service, and
delegates all credential authorization and SQL creation to that service.
Successful HTTP 201 contains only `connection_id`,
`installation_id=telegram-bot`, `enabled=false`, `revision=1`,
and `operational=false`. It does not attach an owner, activate a bot,
register the Telegram webhook, or imply any provider delivery acceptance.

A 403 means provisioning was not authorized. Provider, database, Vault, or
unexpected response failures do not leak the credential handle or raw
provider error. A request can create no operational Telegram transport
without separate activation, live provider identity verification, webhook
registration, identity-linking, and full round-trip acceptance.

The path reuses the already registered Channels router and does not create
a parallel administrative service. Later operator UI should use this same
endpoint and display the returned disabled status without inferring health.

## Governed operator activation

After provisioning a disabled connection with its canonical Vault reference,
a verified channel operator may request **local activation only** using:

`POST /api/channels/personal/operator/telegram/connections/{connection_id}/activate`

The request body is `{"expected_revision": 1}` for a newly provisioned
connection. The API derives tenant, principal and one-action session context
from authenticated Karen state. It rejects foreign, mismatched, already
enabled, non-Telegram or stale-revision connections before asking
RuntimePolicy for `channel.activate`. ChannelHost retrieves the installed
canonical Telegram adapter, fixes the transport configuration to private
text chats, and invokes the existing ChannelActivationService rather than
starting a plugin in the route.

Successful activation runs the transport's live read-only Telegram bot
identity probe, then commits a tenant-scoped revision CAS. The response
contains connection ID, `enabled=true`, the committed revision, and
`provider_identity_verified_at_activation=true`. It explicitly reports
`webhook_registration_verified=false` and `live_connected=false`.
Those two false values are **verification states**, not assertions that
the external webhook is absent or that a provider failed.

Activation is not a remote `setWebhook` operation, a durable guarantee of
process-local adapter readiness across restarts, an account link or an
end-to-end delivery acceptance. The webhook's expected public origin must be
obtained from canonical deployment configuration before implementing any
provider mutation. There is no automatic Telegram retry or webhook
registration in this slice. Failure and revision conflicts never return a
token, provider response body, native URL or Vault reference.

## Canonical public webhook origin (provider mutation prerequisite)

`KAREN_TELEGRAM_WEBHOOK_PUBLIC_ORIGIN` is an optional, operator-controlled,
HTTPS origin in the canonical channel host settings. When the host is enabled,
a configured value must be a lowercase, canonical public DNS hostname with
no userinfo, port, path, query or fragment, for example
`https://hooks.example.org`. Loopback/local names, IP literals,
credential-containing or ambiguous URLs fail startup validation. No value
is inferred from incoming Host or Forwarded headers.

Omitting this variable is valid and leaves provider webhook registration
unavailable. Defining it does not activate any connection, create a webhook,
or prove Telegram can deliver to that origin. It is only a prerequisite for
a later explicit, RuntimePolicy-authorized `setWebhook` workflow that
constructs the exact tenant connection path, validates the effective HTTPS
deployment configuration, and independently reconciles Telegram's response.
Do not expose the configured origin as proof of a live connection.

## Explicit Telegram webhook registration

After an operator provisions and activates a Telegram connection, a separate,
privileged registration operation is available in the existing authenticated
Channels API:

`POST /api/channels/personal/operator/telegram/connections/{connection_id}/webhook`

The body contains only `{"expected_revision": 2}` for a newly activated
connection. The endpoint obtains tenant, user and one-action session scope
from Karen authentication, requests the dedicated
`channel.webhook.register` RuntimePolicy capability, then delegates through
ChannelHost to the installed Telegram adapter. No request may supply the URL,
token, signing secret, provider ID, tenant or arbitrary adapter.

Registration requires the previously validated
`KAREN_TELEGRAM_WEBHOOK_PUBLIC_ORIGIN`. ChannelHost constructs the exact
`/api/channels/webhooks/{tenant_id}/{connection_id}` path and validates the
enabled connection and persisted revision before making the provider call.
The adapter obtains the bot token and signing secret from host-governed
Identity Vault. It sends Telegram `setWebhook` with the canonical URL,
`secret_token`, `allowed_updates=["message"]` and
`drop_pending_updates=false`. It then requires a successful
`getWebhookInfo` read-back with the exact URL.

A validated success response is limited to
`{"provider_registration_verified": true, "live_connected": false}`.
The latter is not a provider-disconnection claim; it means no end-to-end
ChatRuntime delivery was proven. A failed POST or uncertain read-back is
not treated as a successful registration. Because Telegram may accept a POST
before a network timeout or connection revision change, an ambiguous result
must be reconciled with read-only inspection; never blindly retry or claim
a remote rollback. Registration is explicit, not automatic at startup.

**Outstanding limitations:** A provider URL match does not prove the endpoint
is reachable with valid TLS, that inbound secret verification succeeds, that
the sender is linked and authorized, or that ChatRuntime produces a reply.
The current mutation uses process-local and optimistic revision checks; it
does not offer a durable distributed registration lease across independent
host replicas. Operators must avoid concurrent registration with credential
rotation and deactivation until a durable claim protocol is implemented.
Live acceptance remains mandatory.

## Durable provider-registration claim (KWA-01D)

The existing `SqlChannelRepository` now owns a tenant-scoped, durable
Telegram registration claim in
`public.channel_telegram_webhook_claims`. Claims are exclusive per
tenant/connection, versioned by the exact connection revision and a random
claim token, with a bounded expiry for *successful completion*.

Before any remote `setWebhook`, ChannelHost must acquire the claim using the
same PostgreSQL connection-row lock as the lifecycle owner. Concurrent,
stale, previously verified, expired, or uncertain claims do not authorize
a new POST. **Expiry is not a retry permission.** An interrupted worker leaves
a durable `in_flight` record that must be treated as unresolved.

A provider response or successful exact-URL `getWebhookInfo` read-back only
becomes a verified result after token-matched, unexpired SQL completion.
Timeouts, malformed provider responses, changed revisions, expired leases
and other uncertain outcomes must leave the claim `uncertain` or
`in_flight`. The database refuses connection enabled/revision updates
while either unresolved state exists. No provider URL, token, signing secret,
message body or personal data is stored in the claim ledger.

**Operational restriction:** This slice intentionally does not provide a
reconciliation/reset operation. A stale or uncertain claim blocks further
registration and lifecycle transitions until a separate, RuntimePolicy-
authorized read-only reconciliation and recovery path is implemented.
Do not bypass the SQL guard, delete the row manually, or silently retry
a potentially accepted remote mutation.

The claim is scoped to a Karen connection, not yet a globally verified
Telegram bot identity. Reuse of the *same bot token* in another tenant or
connection remains a separate provider-ownership fencing problem and is
not certified by this change. Do not run concurrent registrations for the
same Telegram bot through different connection IDs. Live signed inbound,
linked principal and provider-confirmed ChatRuntime reply still require
actual acceptance testing.

## Read-only registration reconciliation evidence

Authorized channel operators can inspect durable Telegram registration claim
state side by side with a fresh Telegram `getWebhookInfo` read-back:

`GET /api/channels/personal/operator/telegram/connections/{connection_id}/reconciliation?expected_revision=2`

The API requires an enabled, tenant-matching Telegram connection and a fresh
`channel.inspect` RuntimePolicy plan. The canonical repository reads the
tenant-RLS claim ledger without exposing its token. The canonical adapter
uses host-resolved Vault credentials and the configured public HTTPS origin
to compare the exact expected webhook URL against Telegram's live response.

Results contain only the claim state (`absent`, `in_flight`, `uncertain`,
or `verified`), whether its revision matches, whether the lease has
expired, whether Telegram reports any webhook, and whether Telegram reports
the exact trusted destination. They **always** report
`claim_released=false`, `reconciliation_authorized=false`, and
`live_connected=false`.

This endpoint **never** calls `setWebhook` or `deleteWebhook`, clears a
claim, extends its lease, deactivates a connection, or grants retry
authority. A matching URL is a provider observation, not proof of signed
inbound delivery or a provider-confirmed ChatRuntime reply. An uncertain
claim remains blocked even if Telegram currently reports the expected URL.
Durable recovery requires a separate guarded workflow with provider ownership
and cross-replica fencing proofs.

## Reconciliation consistency across remote reads

The host reads the tenant-scoped claim before contacting Telegram and reads it
again after the provider response, alongside a fresh enabled connection revision.
If the claim state, revision-match flag, expiry state, or persisted connection
changes, the inspection fails closed rather than combining stale SQL evidence
with a newer provider response. This has no side effects and never releases
an uncertain claim.

These two read-only checks do **not** create an atomic transaction with the
Telegram Bot API, prove unique ownership of the Telegram bot across tenants,
or authorize recovery. Claim release remains unavailable until independently
fenced provider ownership and durable recovery are implemented.

## Provider-verified global Telegram bot ownership

Telegram supports one configured webhook per bot token. A Karen connection
label or tenant-specific uniqueness constraint cannot prevent two different
tenants from configuring the same bot. The canonical registration workflow
therefore now performs a fresh, read-only Telegram `getMe` probe using the
trusted Vault credential and requires its positive numeric bot ID before
acquiring a webhook mutation claim.

A new globally unique `public.channel_telegram_bot_owners` registry stores
that numeric provider bot ID, owning tenant, connection, and connection revision.
No bot token, signing secret, provider URL, or user text is stored. Global
uniqueness is enforced by PostgreSQL even across tenant-scoped RLS contexts;
no conflicting owner's tenant identity is returned. Claim acquisition and
bot-identity reservation occur in the same database transaction. A duplicate
ID held by another connection aborts the transaction before `setWebhook`,
without leaving a partially acquired webhook claim.

The adapter re-resolves its Vault credential immediately before `setWebhook`
and verifies the provider's `getMe` identity again using the **same bot
token** it will use for the mutation. If a credential changed between the
original ownership reservation and the actual outbound call, the provider
mutation is refused and the durable claim remains unresolved. This rules out
silently registering a different bot after a credential rotation.

A repeat reservation for the *same* tenant, connection, revision, and numeric
bot ID is accepted only as an idempotent ownership check, not as permission to
reuse an existing webhook claim. Changing the credential to a different bot,
switching tenants, or using an older revision fails closed. Owner rows are not
automatically released when a claim expires, when a provider call is uncertain,
or when the process restarts. Foreign keys also restrict deleting a tenant or
connection while a bot ownership record exists, preventing implicit cascade
release without provider unlink evidence.

**Recovery is still separate:** bot ownership release or reassignment needs
durable evidence of provider unlink, credential revocation and a separately
authorized lifecycle transition. No admin UI action or external webhook
inspection may silently clear these rows. The unique owner guard does not
by itself prove a live signed inbound message or a successful AI reply.

## Bot ownership preflight for read-only recovery evidence

The authenticated Telegram reconciliation endpoint now requires the *current*
Vault-resolved Telegram `getMe` numeric bot identity to match an ownership
record in the globally unique `channel_telegram_bot_owners` ledger for the
same tenant, connection, and enabled revision. This lookup runs within the
canonical tenant-RLS repository. A foreign or absent owner is a denial,
not a provider URL diagnostic.

After the external `getWebhookInfo` read, the host rechecks both the
connection/claim snapshot **and** the current provider bot identity and
ownership. A credential rotation or owner transition during observation
invalidates the response. Successful evidence includes
`bot_identity_owner_verified=true`, but still always returns
`claim_released=false`, `reconciliation_authorized=false`, and
`live_connected=false`.

This is only a prerequisite for future governed recovery. It does not grant
a claim reset, authorization to revoke ownership, remote `deleteWebhook`,
or a proof of signed inbound message processing.

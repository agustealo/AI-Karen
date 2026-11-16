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

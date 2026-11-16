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

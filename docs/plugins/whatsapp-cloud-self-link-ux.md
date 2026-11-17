# KWA-01C6C2B2: Consumer self-link UI for managed WhatsApp Cloud

This UI is a thin authenticated client to the canonical host-issued
`channel.link` action from KWA-01C6C2B1. It does not own a provider adapter,
identity store, secret Vault, policy plan, chat execution or delivery status.

## User workflow

In **Settings → Personal → Channels**, a signed-in, verified Karen user
can explicitly select **Find available WhatsApp Cloud connections**. Karen
returns only currently enabled canonical WhatsApp Cloud connections in that
user's tenant, guarded by the existing `channel.link` permission and a fresh
RuntimePolicy decision. The user chooses an actual returned UUID before
requesting a proof. They may also enter an operator-provided UUID manually
as a compatibility option. No connection is guessed, selected or linked
automatically.

### Governed connection discovery

```text
GET /api/channels/identity/whatsapp/connections
```

The existing identity ingress authenticates the session and requires an
active, verified account. The canonical host checks the installed WhatsApp
adapter, existing `channel.link` ActionExecutionGate, fresh role/tenant
RuntimePolicy decision and bounded SQL repository. PostgreSQL additionally
joins the same active verified `auth_users` principal, enforces tenant RLS,
filters `installation_id = 'whatsapp-cloud'` and `enabled = true`, orders
deterministically, and refuses more than 50 results.

Each returned choice contains **only** `connection_id` (UUID) and
`connection_revision` (positive integer). No phone numbers, provider
account IDs, Vault handles, sender identities, activation tokens or
credential state are queried or returned. Empty means the host returned no
currently enabled eligible tenant connection rows, **not** that Meta is
offline or that a live provider test failed. Client parsing rejects extra
fields, duplicate IDs, malformed revisions, and unbounded result sets.

The GET endpoint responds with `Cache-Control: no-store, private`.
Retrieval is opt-in, and the UI never issues a link command simply because
one connection exists. Changing the selection clears an existing bearer
command and any previously inspected challenge reference; an in-flight
inventory response cannot restore state after principal unmount.

After the user explicitly selects **Request one-time link command**, the app
posts an empty object to:

```text
POST /api/channels/identity/whatsapp/connections/{connection_uuid}/challenge
```

The canonical API authenticates the user, asks
`ChannelActivationService.issue_action_plan(channel.link)` for a scoped RBAC
and RuntimePolicy decision, then invokes the existing
`ChannelLinkService.issue_challenge` through `ChannelHostServices`.

Only a successful, strictly validated response (one UUID, exact
`/link <43-character token>` pattern, and 60–900 second lifetime) can
display the one-time command. No command is saved to localStorage, cookies,
URL query strings, session history, browser logs, analytics, a toast or a
second source of truth. The component is keyed to authenticated tenant/user
identity; it clears on logout, principal change, changing connection, explicit
dismissal and the host-declared lifetime. The clipboard is modified **only**
when the user explicitly clicks Copy, and the user is instructed to clear
clipboard contents after sending.

The user sends the exact command from their own WhatsApp sender to the
operator-approved business test number. A successful HTTP challenge response
**does not** establish sender binding or WhatsApp connectivity. Real Meta-signed
native `/link` ingress must consume the digest-only one-use proof within the
same tenant, connection revision and expiry. Ordinary messages then require
fresh current principal checks and are executed only by canonical ChatRuntime.

## Read-only proof status after sending

The consumer may explicitly select **Check link proof status** after sending
the one-time command. The UI calls the authenticated, no-cache endpoint:

```text
GET /api/channels/identity/whatsapp/connections/{connection_uuid}/challenges/{challenge_uuid}/status
```

The challenge UUID is a non-secret lookup reference, **not** the one-time
bearer token. The exact active verified tenant/user principal gets a new
`channel.link` RuntimePolicy and RBAC decision. `ChannelHostServices`
checks the canonical installed WhatsApp transport and the existing activation
gate before the original SQL repository reads a record joined to the matching
tenant, user, connection and challenge. RLS enforces the tenant again.

The database reports one of five statuses using its own clock and original
connection revision:

| Status | Precise meaning |
| --- | --- |
| `pending` | No recorded consumption, not a provider delivery failure |
| `consumed` | Original one-use proof was consumed by Karen's signed native ingress, **historical** evidence only |
| `expired` | No consumption before the database expiry time |
| `revoked` | The unconsumed challenge was revoked or replaced |
| `invalidated` | The owning connection is disabled or its revision has changed |

A missing or foreign challenge returns **404**, not a fabricated pending or
success state. The response has `Cache-Control: no-store, private` and
`Pragma: no-cache`, and exposes **no** token, digest, sender ID, account ID,
user ID, binding ID or provider message ID. Every response explicitly reports
`evidence_basis=host_link_challenge_ledger`,
`current_binding_verified=false` and `delivery_verified=false`.

The browser **does not poll** or automatically copy the token. A deliberate
status check is required. Any completed or invalidated status removes the
secret command from memory immediately; expiry also removes the command even
without a check. The non-secret challenge reference can remain available
for an explicit check after expiry. Clearing the panel, changing connections
or changing authenticated user/tenant removes that reference as well. Stale
asynchronous responses cannot restore a cleared command or stale status.

The `consumed` state is **not** proof that a sender binding is still active
today. It does not prove a model response, Meta provider reachability, or a
delivered/read reply. Operator-observed live trial lineage remains a
**separate** evidence path (KWA-01C6C2C1).

## Source verification

```bash
cd src/ui_launchers/Karen-AI-Theme
npx vitest run tests/settings/whatsapp-cloud-self-link.test.tsx
npm run typecheck
npm run build
```

Backend proof runs from the repository root with:\n\n```bash\npytest -q tests/extensions/test_whatsapp_self_link_api.py tests/extensions/test_channel_link_repository.py\n```\n\nThe source suite additionally exercises opt-in connection discovery, strict
untrusted result parsing, no automatic challenge issuance, secret-safe errors,
and a real disposable PostgreSQL test for enabled-only tenant choices,
unverified principals and connection disablement.

Unit tests use mocked API **response contracts** only, not simulated Meta
transport success. They cover empty/invalid UUIDs, explicit request only,
redacted authorization failures, fake provider claims, precise response shape,
request cancellation, TTL cleanup and clipboard opt-in. Existing
`ChannelsSettings` remains the sole consumer navigation owner.

## Release boundary

Source CI cannot prove a live user reached the panel on an approved deployment,
that an operator provided a real WhatsApp business number, that Meta delivered
the signed one-time command, or that identity linking/ChatRuntime/outbound
delivery occurred. No consumer-ready claim or plugin catalog publication is
permitted until live, exact-deployment acceptance independently verifies
those gates. Review `docs/plugins/whatsapp-cloud-shipping.md` for the full
Meta provider acceptance checklist.

## Opt-in real-browser navigation (read-only)

A separate Playwright observer covers the real signed-in consumer at 390, 768,
and 1440px. On an **approved exact-revision HTTPS deployment**, use a verified
sandbox Karen account and export `KAREN_BASE_URL`,
`KAREN_WHATSAPP_DEPLOYMENT_REVISION` (40-character reviewed commit SHA),
`KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` by the operator's secret injector.
Then run from `src/ui_launchers/Karen-AI-Theme`:

```bash
KAREN_WHATSAPP_SELF_LINK_UI_ACCEPTANCE_REQUIRED=true \
npx playwright test e2e/whatsapp-cloud-self-link-ui-acceptance.spec.ts \
  --config=e2e/playwright.config.ts --project=chromium --retries=0
```

It follows dashboard **Application Settings → Personal → Channels**, checks
the native one-time link panel, rejects malformed UUID input, and proves that
read-only observation issues **no** identity challenge POST. The test never
requests, displays, records or copies an actual proof command, and Playwright
traces/screenshots/video stay disabled. A skip or green source CI is **not**
real-deployment acceptance and is not Meta-signed provider evidence.

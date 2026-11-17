# KWA-01C6C2B2: Consumer self-link UI for managed WhatsApp Cloud

This UI is a thin authenticated client to the canonical host-issued
`channel.link` action from KWA-01C6C2B1. It does not own a provider adapter,
identity store, secret Vault, policy plan, chat execution or delivery status.

## User workflow

In **Settings → Channels**, a signed-in and verified Karen user can enter
a WhatsApp Cloud connection UUID supplied by their authorized tenant operator.
It is never fetched from another tenant or guessed from the UI.

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

## Source verification

```bash
cd src/ui_launchers/Karen-AI-Theme
npx vitest run tests/settings/whatsapp-cloud-self-link.test.tsx
npm run typecheck
npm run build
```

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

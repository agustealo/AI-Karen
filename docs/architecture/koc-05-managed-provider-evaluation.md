# KOC-05 Managed Personal WhatsApp Provider Evaluation

Status: **candidate research only; no vendor approved or enabled**.
Last reviewed: 2026-10-18.

## Required split of responsibilities

- **Official business account:** use WhatsApp Cloud API. Where eligible,
  the WhatsApp Business App can coexist with Cloud API using Meta Embedded
  Signup. That is **not** personal/consumer WhatsApp linked-device access.
- **Personal consumer WhatsApp:** unofficial companion-device integration,
  requiring a separately consented and tightly scoped managed vendor with
  an explicit account-suspension, privacy and provider-custody notice. Never
  describe this route as endorsed by WhatsApp or equivalent to Cloud API.
- **Karen authority:** installation catalog, RuntimePolicy, tenant identity,
  CredentialVault, durable owner/consent/pairing state, action audit,
  anti-replay, response truthfulness and data deletion verification.
- **Vendor authority:** actual provider session creation, QR production,
  live session health, native webhook proof, remote logout and verifiable
  erasure of retained device credentials. Karen must not simulate any of these.

## Candidate fact-finding (documentation, not acceptance)

| Candidate | Documented fit | Blocking evidence / concern |
| --- | --- | --- |
| WALayer | Hosted sessions, QR/pair-stream, session health, upstream logout, and DELETE described as credential shred | Require verified webhook cryptography, precise encrypted credential custody, enforceable retention/deletion proof, source-contract version pinning, rate limits, signed event semantics and live test with vendor account |
| WasenderAPI | Managed session creation, QR, status webhooks, session disconnect/delete | Published webhook example checks `X-Webhook-Signature` against a shared secret (rather than body HMAC); **incompatible with Karen's current exact-body HMAC decoder** unless a separately authenticated, tested canonical adapter normalizes it. Delete documentation says it *attempts* disconnect first, not proof of upstream logout and secret erasure |
| Self-hosted WhatsApp Web API implementation | Several open-source libraries document QR/device and disconnect functions | Rejected for this slice: user explicitly requests no extra self-hosted messaging service. Repo claims of production readiness do not constitute security/provider approval |
| Official WhatsApp Business Cloud API / Coexistence | Supports official business messaging and, for eligible existing Business App accounts, coexistence through Embedded Signup | Not a consumer-personal WhatsApp linked-device integration. Business App eligibility, lifecycle and onboarding constraints must be separately verified |

Source references (reviewed 2026-10-18):
- https://walayer.com/docs
- https://wasenderapi.com/api-docs
- https://wasenderapi.com/api-docs/webhooks/webhook-setup
- https://wasenderapi.com/api-docs/webhooks/webhook-session-status
- https://wasenderapi.com/api-docs/webhooks/webhook-qrcode-updated/
- https://developer.8x8.com/connect/docs/whatsapp/whatsapp-business-app-coexistence/
- https://faq.whatsapp.com/1428782138011916/

## Mandatory approval gates before any activation

1. **Vendor approval:** explicit human security/compliance review, signed
   commercial terms and credible data-processing, jurisdiction, retention
   and incident-response disclosures. Audit how vendor stores WhatsApp Web
   companion credentials, messages, media and phone number identifiers.
2. **Native authentication:** independently verify signature semantics using
   vendor documentation and captured signed *test* events. Static shared
   secret headers cannot be treated as HMAC over message bytes. Build a
   provider-specific transport adapter that verifies native format and
   emits a canonical `PairingObservation`; never let a raw provider event
   set `authenticated=True` or `provider_vetted_and_enabled=True`.
3. **Scoped identity:** bind `tenant_id`, `connection_id`,
   `installation_id`, provider session ID and connection revision.
   Obtain the provider session ID through an operator-governed, durable
   creation transaction. Never accept caller-provided session IDs/URLs.
4. **QR handling:** deliver only a short-lived one-use QR after current
   consent, owner/RBAC and configured-vendor checks. Do not persist raw
   QR string, URL or image in logs, caches, analytics or generic chat state.
   Cache-Control: no-store; no cross-origin embedded QR image service.
5. **Live state:** get a fresh authenticated provider health result and
   correlate its session/revision; historical `connected` receipts and
   `configured` provider declarations are *not* live connectivity.
6. **Remote teardown:** revoke local authorization immediately; invoke
   vendor logout with idempotency and separately verified ack; request
   credential and data erasure; preserve audit evidence without retaining
   credentials. If vendor is unreachable, label `disconnect_pending`,
   schedule governed retry, and give user manual Linked Devices logout
   instructions. Never claim provider_unlinked from an HTTP 200 alone.
7. **Operational proof:** test missing/forged/late QR, duplicate webhooks,
   key rotation, concurrent pair/revoke, cross-tenant retrieval, offline
   vendor, HTTP 429/5xx, account ban, session theft, stale status, deletion
   receipts, and production-like authenticated UI screenshots.
8. **Release gating:** default-off feature flag plus passing unit,
   PostgreSQL integration, API/RBAC, UI contract, and end-to-end tests.
   Human verification before consumer activation or distribution packaging.

## Current decision

**None approved.** Keep `KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON`
empty in default runtime. The existing internal HMAC contract is a
canonical integration boundary, **not evidence any candidate implements it**.
Choose a provider only after steps 1 and 2. Do not build an adapter using
guessed native endpoint schemas or spoofed statuses.

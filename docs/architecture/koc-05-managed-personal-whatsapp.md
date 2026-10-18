# KOC-05: Managed Personal WhatsApp QR pairing

## Decision
Karen offers Official WhatsApp Business Cloud API separately from optional personal WhatsApp Linked Devices. Personal Linked Devices uses an unofficial WhatsApp Web client managed by a vetted third party. It is disabled and unavailable until qualified provider integration is implemented.

## Exact user disclosure
Title: Connect personal WhatsApp (unofficial integration)

This connection is not supported or endorsed by WhatsApp/Meta. Your account may be restricted or permanently banned. An unofficial linked client may technically access messages and metadata outside conversations that Karen is authorized to process. Sensitive session credentials can be abused if compromised. Protocol changes can interrupt connectivity. A third-party operator adds a data recipient and security dependency. Disconnect does not guarantee deletion of previously collected provider data.

The user must explicitly accept a versioned risk notice. A browser checkbox is NOT consent evidence. Only a persisted, server-issued, tenant/user/connection/provider-scoped record is valid. A changed policy version or revoked consent requires fresh acceptance.

## Controls
- Common Connect → Verify → Enable → Connected → Disconnect flow.
- Never fabricate QR, pairing success, connection health, unlink success or credential deletion.
- Verify current principal, RBAC and RuntimePolicy before any provider action.
- Require a vetted, explicitly enabled managed provider; no self-hosted gateway.
- One-use QR, short TTL, no raw QR/credentials/session keys in logs or memory.
- Default only self-chat; no contacts, groups, media, history import or proactive messaging.
- Store opaque credential references; govern ingress and outbound via existing ChannelHost and SQL claims.
- Unknown provider sends are never automatically replayed.
- Disconnect requires separate provider unlink and data deletion receipts; display actual status.

## Provider review
Evolution API is an open-source potential transport engine, not proof that a secure managed provider exists. Vet any operator for tenant and session isolation, data residency, retention and deletion, authenticated callbacks, account unlink, SLA, breach process, legal restrictions, and shutdown behavior.

Source: https://faq.whatsapp.com/378279804439436/
Project: https://github.com/evolution-foundation/evolution-api

## Acceptance
- [x] Fail-closed eligibility and versioned consent scope evaluator with tests.
- [ ] Durable consent store, versioned audit and revocation flow.
- [ ] Qualified third-party provider and adapter with authenticated inbound webhook.
- [ ] Live pairing, QR expiry/replay, reconnect, tenant, unlink and deletion proof.
- [ ] One truthful Channels UI driven exclusively by backend connection state.

Policy assessment is NOT an external pairing token. The governed activation path must still revalidate before side effects.

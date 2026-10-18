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
- [x] Tenant-scoped consent store, versioned acknowledgement history and revocation repository.
- [x] Dedicated channel.consent user permission and operator-assigned connection ownership gate.
- [x] Operator-gated one-time owner assignment through canonical ChannelHost + SQL, with audit event.
- [ ] Authenticated consumer endpoint, live provider pairing and proof of operator/owner experience.
- [ ] Qualified third-party provider and adapter with authenticated inbound webhook.
- [ ] Live pairing, QR expiry/replay, reconnect, tenant, unlink and deletion proof.
- [ ] One truthful Channels UI driven exclusively by backend connection state.

Policy assessment is NOT an external pairing token. The governed activation path must still revalidate before side effects.

## Self-consent permission boundary

Normal users have only channel.consent through the canonical RBAC registry. They
cannot provision, activate, send, recover, or manage other people's connections.
The channel host first reads the exact tenant-scoped connection and its
operator-assigned channel_connection_owners row, then evaluates current
principal/RuntimePolicy with channel.consent. Consent SQL also joins owner
assignment before accepting the risk acknowledgement, independently of host
validation. The owner ledger cannot be created by the consent action.

The owner is still assigned by a separate governed administrative process,
which must be implemented and audited before a self-service QR UI goes live.
A persisted acknowledgement is never sufficient to create a QR or claim a
provider-linked session; no managed Baileys operator has been approved.

## Owner assignment authority

ChannelHost.assign_personal_connection_owner requires the canonical channel.provision
operator authorization. SqlChannelRepository inserts a verified active user's
ownership at most once for the tenant's existing connection. Conflicting
owners and duplicate assignments do not overwrite existing owners, thereby
preserving any consent bound by the foreign key. The user-facing channel.consent
action only reads the assigned owner and cannot call owner assignment.

Before consumer release, a distinct authenticated API handler must supply the
verified actor identity/session (not a request body claim) and issue a fresh
canonical action plan. Provider connection and managed session enrollment need
independent acceptance gates and can never be assumed from an owner row.

## Authenticated user risk consent endpoints (implemented, provider still disabled)

- POST /api/channels/personal/{connection_id}/{provider_id}/consent accepts only
  explicit accepted=true and the current policy version.
- POST /api/channels/personal/{connection_id}/{provider_id}/revoke revokes the
  caller's risk acknowledgement without pretending a linked device was unpaired.
- Both routes use the existing get_current_user authentication dependency and
  resolve durable tenant and user UUIDs from that principal. No caller-supplied
  actor, tenant, session ID, RBAC plan, or installation ID is trusted.
- Each request creates a fresh server-side policy execution context and asks
  ChannelActivationService.issue_action_plan for channel.consent. The host
  revalidates owner, principal and plan before the repository side effect.
- These endpoints do not provide a live provider token or QR; paired and
  provider_unlinked remain explicitly false. Consent alone cannot create a
  session and cannot initiate an outbound message.
- The client must not treat acknowledged=false on repeated acceptance or
  revoked=false on repeated revocation as a provider connection state.
- A separately authenticated and audited operator provisioning endpoint and
  vetted managed provider are required before users can begin pairing.

## Read-only consumer consent status

GET /api/channels/personal/{connection_id}/{provider_id}/consent uses the
same authenticated identity, exact persisted connection ownership, fresh
channel.consent policy plan, and ChannelHost read authority as accept/revoke.
It reports a policy-version-matching, unrevoked acknowledgement only.
Neither acknowledged nor revoked consent establishes a real QR session.
The response explicitly reports paired=false and provider_unlinked=false;
provider status must be a separate verified transport-owned observation.

## Provider-evidenced QR lifecycle contract (pure reducer)

The new personal_pairing_lifecycle module is a **pure transition validator**.
It neither runs Baileys nor issues QR codes. Only a verified provider adapter
may create authenticated observations, and the existing ChannelHost must commit
them through a durable connection-revision/sequence compare-and-swap after
revalidating active consent and provider eligibility.

States: ready, qr_available, connected, disconnect_pending, disconnected,
unknown. QR receipt is short-lived (five minutes maximum) and bound to
connection revision. A linked state requires a nonempty verified provider
receipt while the QR is still live. Disconnect requested never means unlink
confirmed; the latter requires a distinct provider receipt. Failure or
uncertain status remains unknown, without silent retries or optimistic UI.

Do not publish these states as live provider truth until session persistence,
signed provider events, actual managed operator health, replay fencing,
credential revocation and one-use QR retrieval are implemented and tested.
A pure reducer alone is never a complete connection lifecycle.

## Durable pairing state (migration 34)

The existing SqlChannelRepository now owns an *internal-only* transaction to
commit verified personal pairing observations. Migration 34 holds the
tenant/connection/provider/revision-scoped phase and sequence with FORCE RLS;
it stores no QR bytes or session credentials. This operation locks the parent
channel_connections row and reads the operator-assigned owner and latest
consent **inside the same transaction** before applying the pure reducer and
persisting one revision-fenced sequence transition. Concurrent submissions
of the same sequence cannot both commit. Stale connection revisions fail
closed; any connection owner other than the assigned verified user is rejected.

New QR creation and link confirmation still require the current policy
version and operator eligibility. Confirmed provider unlink and failure can
be recorded even after consent revocation or provider disablement. The
service must not infer actual provider authorization from a Boolean field in
an event: the future trusted host must authenticate the provider's event,
verify a configured/vetted operator and do provider health/revocation checks
before calling this repository method. There is intentionally **no public
route** to write observations. The method is not a runnable Baileys adapter.

The dedicated disposable PostgreSQL test includes a two-session race against
the actual repository SQL; it asserts one winner, stale/replayed event
rejection, foreign owner denial, explicit link and unlink receipt recording,
and safe revocation. Those tests must pass CI on the current commit before
this slice can be considered verified. Vendor/operator and UI state remain
blocked until real provider evidence exists.

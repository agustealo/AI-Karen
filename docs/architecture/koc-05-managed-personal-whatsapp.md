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
- [x] Authenticated operator owner-assignment endpoint with fresh channel.provision authority and fail-closed conflicts.
- [ ] Authenticated consumer endpoint, live provider pairing and proof of operator/owner experience.
- [ ] Qualified third-party provider and adapter with authenticated inbound webhook.
- [ ] Live pairing, QR expiry/replay, reconnect, tenant, unlink and deletion proof.
- [x] Read-only personal Channels inventory/settings driven by backend connection state (no pairing controls).
- [x] Versioned consumer risk notice, explicit consent acknowledgement and revocation UI, with backend-confirmed reads (no session or QR).
- [x] Owner-scoped legacy consent discovery and revoke-only UI after managed provider removal from configuration or consent-policy rollover.
- [x] Transport-independent consent recovery for retired ChannelHost or uninstalled adapter, using existing RBAC, RuntimePolicy and SQL revocation lock.
- [ ] Full governed Connect → Verify → Enable → Connected → Disconnect UI with live provider evidence.

Policy assessment is NOT an external pairing token. The governed activation path must still revalidate before side effects.

## Self-consent permission boundary

Normal users have only channel.consent through the canonical RBAC registry. They
cannot provision, activate, send, recover, or manage other people's connections.
The channel host first reads the exact tenant-scoped connection and its
operator-assigned channel_connection_owners row, then evaluates current
principal/RuntimePolicy with channel.consent. Consent SQL also joins owner
assignment before accepting the risk acknowledgement, independently of host
validation. The owner ledger cannot be created by the consent action.

The owner is assigned through the separately authenticated operator-only
endpoint described below; ChannelHost performs fresh authorization and emits
the existing owner-assignment audit event. This administrative assignment
does not make personal QR pairing available. A persisted acknowledgement is
never sufficient to create a QR or claim a provider-linked session; no
managed Baileys operator has been approved.

## Owner assignment authority

ChannelHost.assign_personal_connection_owner requires the canonical channel.provision
operator authorization. SqlChannelRepository inserts a verified active user's
ownership at most once for the tenant's existing connection. Conflicting
owners and duplicate assignments do not overwrite existing owners, thereby
preserving any consent bound by the foreign key. The user-facing channel.consent
action only reads the assigned owner and cannot call owner assignment.

An authenticated operator owner-assignment handler now supplies the
verified actor identity and a fresh server-created policy session, never a
request body claim. The canonical ChannelActivationService issues the
channel.provision plan, ChannelHost revalidates the decision, and the existing
SqlChannelRepository verifies an active, verified tenant user before inserting
an immutable owner row. This is not general channel provisioning, managed
session enrollment or pairing: provider connection, QR issuance and remote
unlink still require separate release gates.

### Operator assignment API (implemented, personal provider still disabled)

- POST /api/channels/personal/{connection_id}/owner
- Request: `{"owner_user_id": "<verified tenant user UUID>"}` only.
  The schema rejects tenant, operator, session, provider and policy-plan
  overrides.
- Requires the existing authenticated get_current_user dependency with a
  verified active durable principal and an existing tenant-scoped connection.
  The connection's installation must also be explicitly allowlisted in
  KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON and declare the
  pairing_webhook_secret Vault type. A generic installed channel cannot use
  this personal owner-assignment API without those gates.
- Requires fresh channel.provision RuntimePolicy/RBAC authorization and
  ChannelHost.assign_personal_connection_owner revalidation.
- The existing SQL transaction assigns the active, verified target user only
  once. A conflicting owner, repeated assignment, missing target or other
  uncommitted assignment returns HTTP 409, not a false success or overwrite.
- Successful HTTP 201 reports owner_assigned=true with paired=false,
  qr_available=false and provider_unlinked=false. No QR, native provider
  session, credential, activation or send is created by this endpoint.
- Authorization denial returns HTTP 403; malformed request HTTP 422;
  unexpected dependency/storage failure HTTP 503 with a redacted error.
  The host emits the canonical owner-assignment structured audit event.
- The route does not grant channel.provision to ordinary users: the
  activation service rereads the current tenant principal, channel manifest
  operator roles and canonical RBAC, and evaluates RuntimePolicy before
  invoking the host/repository owner operation.

Proof:
`pytest -q tests/extensions/test_personal_channel_consent_api.py`
and the existing owner/tenant SQL and RuntimePolicy contract suites.
This does not satisfy the separate live managed-vendor or consumer UI checks.

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
- Operator owner assignment is authenticated and audited as described above.
  General connection provisioning, an independently vetted managed provider,
  and real session pairing are still required before users can begin pairing.

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

## Signed provider callback admission (KOC-05)

A separate **managed-operator callback envelope**, not the WhatsApp Linked
Devices protocol itself, is now implemented in personal_pairing_callback.py.
It accepts exact UTF-8 JSON fields, a bounded body (16 KiB), and an
X-Karen-Pairing-Signature header (HMAC-SHA256 of the original bytes). It rejects
duplicate JSON keys, unknown fields, wrong scope, malformed values, clock
skew beyond five minutes, unsigned or altered bytes and bad signatures. It
does not trust caller-supplied "authenticated" Boolean fields.

ChannelHost.admit_signed_personal_pairing_event is deliberately an **internal
method only**, not a publicly reachable or authorized pairing HTTP endpoint.
It retrieves the durable connection, confirms its installed canonical adapter
and operator allowlist, loads its secret through the existing tenant-scoped
CredentialVault resolver, authenticates the callback, looks up the actual
operator-assigned connection owner and calls the durable, revision-fenced
repository. Raw QR, session credentials and callback bodies are not logged.

Optional validated config:
- KAREN_CHANNEL_PERSONAL_PAIRING_PROVIDERS_JSON is an installation-to-provider
  ID mapping, default empty. It is an operator-approval allowlist, not a way
  for users or provider events to register their own trusted service.
- An explicitly approved installation requires pairing_webhook_secret among
  its host-configured Vault secret types. A malformed or uninstalled provider
  declaration fails startup validation.
- Only explicit operator approval of the deployment and independently vetted
  managed-provider signing/key-rotation protocol permits enabling this mapping.

**Not operational:** No candidate operator is yet approved or connected to
the envelope contract. No public callback route, provider-specific delivery
adapter, QR payload retrieval, live signature interoperability test, customer
connection or authenticated device unlink is implemented. Never display
"connected" based on a persisted HMAC envelope alone; real operator
provenance, session state, expiry, credential unlink and deletion verification
must be proven with end-to-end tests before enabling this configuration.

## Revocation ordering and verified callback admission

The channel host now includes a Vault-secret-HMAC callback verifier scoped to
the configured installed channel provider. This is a **host-only** integration,
not a live Baileys endpoint or proof of a real linked personal account.
Provider callback bytes are authenticated before parsing, and the repository
still checks owner, connection revision, current consent and sequence.

Risk revocation now locks the *same parent channel_connections row* as pairing
observation commits before it invalidates consent. The ordering guarantee is
that once a revocation transaction returns successfully, a pairing commit
that starts later cannot use its old accepted consent. A pairing commit
already serialized ahead of revocation can be recorded before revocation,
which does NOT imply provider unlink; teardown receipt remains separate.
Dedicated PostgreSQL integration coverage checks that revocation blocks
behind a held parent lock and a subsequent link confirmation is rejected.

No managed pairing vendor has been vetted or configured by default. The
callback signing contract is an internal integration prerequisite, not
confirmation that any commercial operator natively supports it.

## Strict managed-provider callback ingress

POST /api/channels/personal/callbacks/{tenant_uuid}/{connection_uuid}
is the only personal-pairing provider callback exemption from normal session
authentication. Its original body is capped at 16 KiB, read once and sent
unchanged to the already canonical ChannelHost; there is no direct SQL,
provider selection or state mutation in the API route. ChannelHost resolves
the installed, explicitly configured personal-pairing provider and Vault key,
authenticates the HMAC over the unmodified body and delegates admitted
observations to revision-fenced repository persistence.

The route returns HTTP 202 only after the host method finishes, never on
missing host, invalid evidence or storage failure. Error responses do not
include signing keys, native bodies or provider messages. No managed vendor
is configured by default, and no QR payload/session is generated.

This is an internal callback integration contract. Any later hosted operator
must be vetted for compatibility with this signed envelope, custody and
deletion/remote-unlink requirements before enablement. The backend's
callback mock tests do not constitute vendor integration testing.

## Provider-bound user consent

A new acceptance is allowed only when the connection installation maps to
the exact managed provider ID in canonical ChannelHostSettings and declares
the Vault-backed pairing_webhook_secret. Runtime policy and the authenticated
connection owner are also checked by ChannelHost; a web client cannot invent
or switch operator identity merely by changing provider_id in the URL.
After provider disablement, reading or revoking previously recorded consent
remains available, so users are not locked out of their audit and privacy
controls. Revoke still does **not** attest remote provider unlink.

## Authenticated personal Channels inventory and settings (read-only)

The existing Channels API now exposes
`GET /api/channels/personal/connections`, using `get_current_user`
without caller-selectable tenant, user, provider or installation arguments.
This is the data source for **Settings → Personal → Channels**, not a new
Channels system or extension manager.

- `SqlChannelRepository.list_personal_owned_connections` executes one
  tenant-RLS SQL query joined against `channel_connection_owners` with the
  exact authenticated `user_id`. The response is bounded at 50 rows,
  failing rather than silently truncating if more are present.
- `ChannelHost.list_owned_personal_channels` checks the host lifecycle,
  rejects cross-tenant or unavailable installations and mints a **fresh
  channel.consent** plan for each connection using the canonical activation
  service. It reuses `get_personal_pairing_status` and its exact SQL
  owner/policy validation, not an independent state machine.
- HTTP returns only `connection_id`, `installation_id`, configured
  `provider_id` (if any), `active_consent_provider_ids` (the owner's
  exact active unrevoked, possibly disabled managed-provider identifiers),
  `availability`, `last_observed_phase`, `live_connected`,
  `qr_available`, and `provider_unlinked`. Credentials, provider account
  identifiers, native events, QR payload and internal authorization plans
  are never serialized.
- Unauthenticated/unverified principals or denied policy fail closed.
  Disabled/missing host remains an explicit error, **not** an empty
  connection list. A valid empty list means no owner-assigned connections
  were returned by the backend, not no installed providers.
- The UI shows backend-provided status only, explicitly labels persisted
  pairing phases as historical and never promotes them to live health.
  Refresh clears the previous view; read errors cannot retain stale
  connected badges. The panel has **no** connect, QR, unlink, delete,
  activation, consent or provider-changing actions.
- Ownership inventory is **not a provider-side live pairing check**.
  Existing consent and read-only status endpoints remain canonical.
  No managed personal vendor is approved by this milestone.

Proof:
`pytest -q tests/extensions/test_personal_channel_consent_api.py
tests/extensions/test_channel_connection_repository.py
tests/extensions/test_channel_host_lifecycle.py`
and frontend
`vitest run tests/settings/channels-settings.test.tsx
tests/settings/settings-ux-ownership.test.ts`
through existing workflows. Provider, session, live browser, authenticated
PostgreSQL and release gates remain separate.

## Versioned personal-channel risk consent UI (implemented, provider still gated)

Under **Settings → Personal → Channels**, each authenticated owner-assigned
connection with a currently configured managed-personal provider can inspect
the current server-issued `policy_version`, `notice_title` and `notice_text`
via the existing `GET .../{provider_id}/consent` route. The disclosure copy
is owned by `services/channels/personal_pairing_policy.py`, alongside its
policy version. The browser does **not** invent consent text, policy version,
tenant/actor identity, provider availability or accepted status.

- The user must read the current server notice and explicitly check the
  unchecked-by-default risk acknowledgement before POSTing
  `{accepted:true,policy_version:<backend version>}`. A checked browser box
  is not durable consent. The backend independently verifies current owner,
  channel.consent RuntimePolicy, provider configuration and SQL scope.
- The UI claims a saved acknowledgement **only after** a positive mutation
  receipt **and a fresh GET** that confirms the persisted current policy
  version and acknowledged=true. An ambiguous write or failed verification
  clears the displayed prior state and requires explicit status refresh;
  no automatic replay or optimistic success.
- For any owner-scoped unrevoked consent, the user can select **Revoke
  consent**, using the existing authenticated `POST .../revoke`. The UI
  displays revoked only after a successful receipt and fresh GET confirms
  `has_active_consent=false` and `acknowledged=false`. Revocation never
  claims remote unlink or provider-data erasure.
- The existing tenant-RLS repository lists at most 16 distinct currently
  active consent provider IDs for each owner-assigned connection. It joins
  active/verified tenant principals, exact connection ownership and
  unrevoked consent, and rejects over-limit results instead of silently
  truncating. ChannelHost performs the usual fresh `channel.consent`
  RuntimePolicy authorization *before* this read.
- The consent GET now distinguishes `acknowledged` (current policy-version
  consent) from `has_active_consent` (any unrevoked consent, including
  previous policy versions). An obsolete consent can be revoked but does not
  count as acceptance of the current policy. Users must revoke the obsolete
  record before any new acknowledgement.
- When the managed provider is removed from its **personal-provider mapping**
  but its canonical channel installation remains authorized and loaded,
  the UI offers **revoke-only** controls for each unrevoked provider ID.
  Neither acknowledgement nor pairing can be initiated in this mode.
  A provider that has been fully uninstalled or a disabled ChannelHost still
  prevents the ordinary consumer API from serving this inventory; an
  independent governed retirement/data-erasure path remains a separate
  lifecycle requirement. Do not claim a complete disconnect or provider
  data-deletion experience from this slice.
- Consent display, mutations and error states remain scoped to the existing
  Channels panel. Official WhatsApp Business Cloud API is separate.

Proof:
`pytest -q tests/extensions/test_personal_channel_consent_api.py`
and frontend
`vitest run tests/settings/channels-settings.test.tsx`
within the existing Main Quality and Plugin Ecosystem workflows. Live
managed provider/QR/session, signed-in browser and credential erasure
acceptance remain NOT_RUN.

## Transport-independent consent recovery after ChannelHost retirement

A disabled ChannelHost or unregistered channel installation cannot satisfy
the ordinary plugin-specific consent authorization. Stored consent must still
be withdrawable without resurrecting the host or its transport.

Under Settings > Personal > Channels, the user can explicitly select
Review stored consent. The action works even when normal channel inventory
is unavailable:

- GET /api/channels/personal/consent-recovery returns a bounded list of at
  most 50 still-active consent references: connection_id, provider_id and
  policy_version. It does not return credentials, provider account details,
  message data or pairing evidence.
- POST /api/channels/personal/consent-recovery/{connection_id}/{provider_id}/revoke
  uses the existing SqlChannelRepository.revoke_personal_pairing_consent
  transaction with its serialized parent-connection lock and owner check.
  Absent or previously revoked consent returns revoked=false.
- PersonalConsentRecoveryService is the one retirement lifecycle for this
  existing consent ledger. It is not a second ChannelHost, provider registry
  or pairing orchestrator. It rereads fresh active, verified tenant identity
  and derives channel.consent permission from canonical RBAC. RuntimePolicy
  issues a new scoped action decision, and the action gate revalidates it.
  No uninstalled plugin is required or trusted as an authority.
- Canonical SQL enforces tenant RLS, active/verified user and exact immutable
  connection ownership before exposing unrevoked consent. Overflow rejects
  the entire inventory. User, tenant, roles and policy tokens are never
  accepted as HTTP claims.
- The frontend never submits a revocation automatically. It requires a
  successful mutation receipt plus a fresh owned ledger read proving that
  the consent record is absent. An ambiguous outcome remains unverified,
  with manual refresh, not an automatic retry. Existing ordinary channel
  consent controls are not duplicated.
- Revocation does NOT prove remote WhatsApp unlink, credential deletion,
  provider data erasure, or the return of a connected transport.

Recovery requires the durable owner, connection and consent rows to still
exist. Deleting a connection cascades its consent evidence. Provider unlink,
data retention and remote erasure need a separate governed retirement
process and verified receipts before destructive connection cleanup.
Absent SQL or fresh auth is a visible failure, not a fabricated success.

Proof: pytest tests/extensions/test_personal_consent_recovery.py
tests/extensions/test_personal_channel_consent_api.py
tests/extensions/test_channel_connection_repository.py, and frontend
tests/settings/channels-settings.test.tsx through the existing CI rails.
Live managed-provider QR, session, remote unlink, erasure and signed-in
consumer browser acceptance remain NOT_RUN.

## User-visible read-only pairing state

GET /api/channels/personal/{connection_id}/{provider_id}/status authenticates
the current user, verifies persisted connection ownership, mints a fresh
channel.consent plan and delegates through ChannelHost to the canonical
tenant-scoped pairing repository.

- availability=unavailable when the installed personal provider is not
  explicitly configured and Vault signing secret is not declared.
- last_observed_phase is only the last persisted, revision-matching event,
  **not** a live managed-provider connectivity probe.
- live_connected and qr_available stay false until a dedicated, current,
  authenticated provider session/QR retrieval protocol exists.
- provider_unlinked is true only for a persisted DISCONNECTED event that
  contains a provider unlink receipt. This confirms the accepted callback
  evidence, not independently audited remote credential erasure.
- Provider status failures never become optimistic UI connected badges.
- No QR contents, provider tokens, stored receipt IDs, or other tenants'
  pairing records are returned in the API response.

## Optional managed pairing transport interface (contract only)

The existing `extensions/channels/contracts.py` now defines a separate
`PersonalPairingTransport` capability with three optional provider operations:
`issue_qr`, `live_session_health` and `unlink_session`. These return
strongly validated `PersonalPairingQR`, `PersonalSessionHealth` and
`PersonalSessionUnlinkReceipt` records, respectively.

- QR payload uses `SecretStr` and a bounded timezone-aware lifetime of at
  most five minutes; raw QR contents must never enter logging, SQL, telemetry
  or chat transcripts. Actual transport APIs, one-time retrieval and issuance
  authorization have not been implemented.
- Live health uses an explicit connected/disconnected/unknown enum and
  requires a provider receipt for a connected observation. A model object
  alone does not authenticate a provider, and its timestamps need host
  freshness checks before consumption.
- Unlink has a distinct provider receipt and timestamp. Remote unlink receipt
  is **not equivalent** to independently verified credential erasure.
- Optional protocols grant no activation: the PluginKernel catalog,
  authenticated host, Vault, RuntimePolicy and durable tenant scope remain
  authoritative. Do not expose these records directly to a browser or
  instantiate a managed vendor until its native API is verified.

## Host-side managed transport evidence freshness gate

The typed vendor interface is not sufficient to assert real connectivity. The
pure `personal_transport_evidence.py` validator now requires exact host-held
provider, connection, revision and provider-issued session scope, an aware
nonfuture timestamp and bounded freshness. QR must remain unexpired; health
observations are limited to 60 seconds by default; unlink receipts are
limited to five minutes. A receipt confirms only the vendor operation it
attests, never credential or data deletion.

These helpers do not authenticate native webhook signatures, deliver QR
payloads, execute lifecycle transitions, enable providers or replace ChannelHost
admission. When an approved vendor adapter is implemented, ChannelHost must
invoke them only **after** native authentication and must enforce current
consent, RBAC, Vault, one-time QR retrieval and durable CAS separately.

Proof: `pytest -q tests/extensions/test_personal_transport_evidence.py`.

## Channel host teardown failure fencing (2026-11-14)

If the canonical ChannelInboxWorker's shutdown raises, the host must still revoke every remaining process-local transport and close its owned HTTP, Vault and PluginKernel dependencies. The host is already marked closed at shutdown entry and must never permit a second teardown or adapter activation. The host records only the worker exception type, completes the existing best-effort dependency cleanup, and then re-raises the original failure (including cancellation) so operational monitoring is not given a false successful stop. No automatic worker replay, provider reactivation, new host owner, migration, or consumer packaging dependency is introduced.

Proof: `pytest -q tests/extensions/test_channel_host_lifecycle.py`, alongside existing channel and Main Quality gates. This source-level shutdown resilience is independent of Render deployment, vendor integration, and live consumer pairing acceptance.


## Retired provider credential-deletion request visibility (read-only)

The consent recovery service can inspect the existing KOC-07 credential-deletion
request ledger after ChannelHost or its adapter is retired. This does not create
deletion requests, call a provider, verify a vendor claim, or authorize cleanup.

- GET /api/channels/personal/consent-recovery/deletion-requests requires the
  same fresh, active/verified tenant principal, channel.consent RBAC,
  RuntimePolicy and ActionExecutionGate as stored-consent recovery.
- Tenant FORCE RLS, exact immutable connection ownership, active verified user
  joins, and a hard 50-row cap gate SQL reads. An absent owner or connection
  cannot be reconstructed from provider-supplied identifiers.
- Returned fields are only request_id, connection_id, provider_id,
  connection_revision and persisted status. No session reference, credential
  scope, Vault handle, provider receipt identifier, contact or message data
  leaves the SQL owner.
- `provider_claimed` describes an authenticated provider **claim** recorded
  by Karen, not independently proven erasure. Even `verified` is only a
  historical ledger label at this endpoint, not a new live verification or
  authorization to delete the connection.
- An empty ledger says only that no retained request exists. Connection
  deletion currently cascades the request, consent and pairing evidence, so
  missing records do **not** prove remote unlink, erasure or absence of data.
- No DELETE route or provider retirement side effect is introduced. Destructive
  cleanup remains explicitly NOT_READY until independent provider unlink,
  credential and retained-data verification, revision-safe export/retention
  and a governed operator deletion transaction exist.

Proof: tests/extensions/test_channel_connection_repository.py,
tests/extensions/test_personal_consent_recovery.py,
tests/extensions/test_personal_channel_consent_api.py and the existing quality
and security CI checks. Live provider and consumer acceptance remain NOT_RUN.


## KOC-05 connection-retirement evidence guard (migration 50)

The 2026-11-14 migration changes the connection-to-personal-evidence
foreign keys for owner assignment, risk consent, pairing state and credential
deletion requests from ON DELETE CASCADE to deferred ON DELETE NO ACTION.
A direct connection deletion with retained personal evidence therefore fails
at transaction commit instead of silently erasing consent and deletion history.
This protects revoked consent history too, not only currently active consents.

The existing tenant-owned tables retain explicit ON DELETE CASCADE tenant
foreign keys, and the credential-deletion ledger gains an explicit user
erasure FK, to keep authorized tenant/account erasure separate from
unreviewed single-connection retirement. PostgreSQL referential actions
remain internal to the database, while ordinary tenant roles have only
SELECT, INSERT and UPDATE policies on the four personal-evidence tables.
There is intentionally no direct DELETE policy for their normal RLS role.

This is a **guard**, not a finished retirement protocol. A privileged SQL
actor capable of bypassing RLS can still deliberately delete evidence,
and account/tenant deletion can intentionally cascade privacy data.
Full retirement still needs separately authenticated provider unlink,
independent credential/data verification, governed evidence retention,
operator RBAC, audit receipts and a dedicated revision-fenced cleanup path.
No provider execution, QR, credential erasure or external-data removal is
claimed by this migration. Existing user consent withdrawal is an UPDATE,
so it remains available after provider or ChannelHost retirement.

Proof runs with the existing disposable PostgreSQL channel contract:
`CHANNEL_TEST_DATABASE_URL=<dedicated karen_channel_test DSN> pytest -q
tests/integration/test_channel_claim_concurrency_postgres.py`.
That suite must prove direct deletion rejection, retained consent/deletion
status, non-owner RLS DELETE denial, and tenant-erasure compatibility.


## KOC-05 owner-scoped retirement-evidence inspection (read-only)

The existing transport-independent consent recovery path offers authenticated
`GET /api/channels/personal/consent-recovery/retirement-evidence` using the
same fresh active/verified principal, channel.consent RBAC, RuntimePolicy and
ActionExecutionGate as consent withdrawal. It reads only tenant-RLS SQL, not a
retired ChannelHost, plugin or third-party provider. User identity and tenant
are derived exclusively from session authentication.

The hard-limited 50-connection snapshot reports each owned connection's
revision and enabled state, outstanding consent, unresolved pairing
observations, presence of credential-deletion requests and unverified
requests, unfinished inbound work and outbound work without confirmed
delivery. It does not return secret handles, accounts, provider receipts,
messages, session references or raw participant identifiers. Overflow
or malformed identity fails closed.

No value in this report authorizes deleting, unlinking, erasing or retiring
the connection, even if every flag is false: a persisted vendor receipt is
not independent current verification, and a read snapshot can become stale
after the transaction. Governed revision-fenced operator cleanup, external
verification and retention policy remain NOT_READY; no destructive API or
provider action was added.


## Credential-deletion ledger transition integrity (migration 51)

The canonical provider erasure receipt is only a provider **claim**, not
independently verified erasure. Migration 51 protects the existing KOC-07
ledger with one database trigger that rejects any new `verified` request
on INSERT or UPDATE. The old `verified` label, if present in historical
rows, stays readable but is not newly authenticated or upgraded. Verified
status is deliberately **unavailable** pending a distinct, governed,
independently evidenced verifier.

A persisted request's tenant, owner, connection, revision, provider,
session reference, credential scope, idempotency key and creation timestamp
are immutable. Once recorded, a provider receipt identifier cannot be
substituted. Only the canonical requested -> provider-pending ->
provider-claimed path and limited fail-closed unknown/verification-pending
transitions are allowed. No replay from unknown or downgrade to requested
can manufacture a fresh deletion claim. The existing service can continue
to persist an authenticated vendor's typed `provider_claimed` receipt
and return it idempotently, but no receipt equals proof of remote backups
or retained-message deletion.

These constraints are database-integrity safeguards, not a new verifier,
provider integration, authorization grant or compliance deletion flow.
A privileged database administrator can disable triggers or execute a
reviewed data-recovery procedure; any historical import must explicitly
account for those privileges and audit rather than silently rewriting
recorded history. User and tenant erasure retain their existing FK cascade
semantics. Ordinary deletion of the whole connection remains guarded by
migration 50.

The disposable PostgreSQL channel acceptance test applies migration 51
after migrations 35 and 50, rejects forged `verified` inserts/updates,
rejects request-scope edits and receipt substitution, exercises the
canonical idempotent provider claim, and confirms the retirement evidence
still reports the claim as unverified. No consumer-package dependency.


## KOC-05 durable operator retirement hold (migration 52)

The first *non-destructive* retirement stage is implemented through canonical
owners only. An authenticated operator may explicitly submit
`POST /api/channels/personal/{connection_id}/retirement-hold` with
`expected_revision` and a UUID `idempotency_key`. Neither tenant, operator
identity, owner identity, provider receipt nor policy plan can be supplied by
HTTP. The route resolves tenant/operator from the active verified session and
mints an existing `channel.deactivate` action grant through
`ChannelActivationService.issue_action_plan`. The host rechecks installation,
live principal, manifest roles, RBAC, RuntimePolicy and ActionExecutionGate,
then delegates exactly one mutation to `SqlChannelRepository`.

The repository transaction locks the exact tenant connection row, verifies a
current verified personal owner and operator, rejects stale connection
revisions, and commits both (a) `enabled=false`, revision increment,
`retirement_locked=true`; and (b) an immutable, owner-and-operator-scoped hold
with original revision and idempotency key. Replay of the *same* caller,
revision and idempotency key returns the original hold without repeating the
local stop; a changed caller/key/revision gets a 409 conflict. A connection
without a verified assigned owner cannot enter this personal hold path.

The database activation trigger prevents direct SQL re-enablement and
canonical `channel.activate` while the hold or the irreversible connection
fence exists. Disabling the channel invalidates stale ingress/dispatch
revision checks on all replicas. The process-local channel adapter's
`stop(connection=...)` is attempted **after** the transaction: its observed
success/failure is returned separately and audited, with no provider data
exposure. An adapter returning from `stop` is NOT proof of vendor unlink
or remote erasure. A failed or cancelled local stop does not roll back the
already durable admission fence. No retry replays a possibly side-effecting
adapter stop, and a manual operator reconciliation remains required.

The owner-facing existing retirement-evidence inspection now includes the
`retirement_held` flag derived from the irreversible connection fence.
The ledger has no regular tenant UPDATE/DELETE RLS policy, so direct callers
cannot erase or rewrite holds. Tenant/account erasure may remove the
personal audit hold through governed FK cascades; `retirement_locked` is
retained on a surviving connection, preventing account erasure from silently
restoring channel activation. Operator principal identifiers follow the
tenant's audit-retention policy; this slice does not define a separate
data-subject erasure protocol.

This stage is **not** full retirement. No provider session unlink, real
credential deletion, independent erasure verification, removal of historical
inbound/outbound messages, cleanup of Vault references or physical connection
deletion is performed or implied. The consumer UI has no destructive action.
The active host/installation must be available for operator authorization;
if absent, the hold endpoint fails closed while consent recovery and
read-only evidence remain available. Full vendor retirement, with independent
source-authenticated receipts and retention/backup policy, remains NOT_READY.

Proof extends the canonical repository, host and API tests and the existing
disposable PostgreSQL channel integration: atomic state/hold commit, exact
idempotency, stale/foreign owner rejection, concurrent operators, non-owner
tenant RLS UPDATE/DELETE denial, irreversible reactivation failure, and
privacy account/tenant cascade. CI remains in the existing plugin workflow,
with no secondary CI path and no consumer packaging requirement.

Retirement also fences any new consent acceptance and pairing observation in
the canonical repository SQL. A user may still revoke existing consent after
the hold, but neither a fresh acknowledgement nor even a manually planted
consent can authorize a new QR/link observation for a held connection. The
disposable PostgreSQL test proves this condition against the live revision.


## Post-hold terminal evidence continuity (KOC-05)

A revision-fenced local retirement hold never reactivates a personal
connection or accepts new QR/link observations. The original vendor session
may still deliver an authenticated disconnect/unlink observation, or claim
credential deletion, after the local hold increments the connection revision.
Without a narrowly scoped continuation, that evidence is stranded.

The canonical repository accepts only `disconnect_requested`,
`unlink_confirmed`, or `failed` observations on a preexisting pairing row
whose revision equals the immutable hold's requested_revision, while the
disabled, retirement-locked connection's current revision equals the hold's
fenced_revision. The signed callback remains admitted solely by the existing
ChannelHost verifier. The existing reducer still enforces ordered teardown
events and a nonempty unlink receipt. New pairing, QR, unlinked sessions,
replays, wrong revisions, missing holds and wrong tenants remain rejected.

The same connection lock permits credential deletion request creation and
idempotent `provider_claimed` receipt persistence for the precise original
session revision after a hold. Newer revisions, missing/mismatched holds, or
foreign scopes are rejected. Migration 51 still prohibits newly inserted or
updated `verified` status.

Read-only owner retirement evidence includes `provider_unlink_claim_recorded`
for a disconnected snapshot carrying an unlink receipt matching the original
hold revision. This is a vendor **claim**, not independently verified unlink
or proof of deletion. UI labels reflect that difference. The feature adds no
provider, deletion path, duplicated service or authorization grant.

The existing real PostgreSQL integration test covers post-hold terminal
observations and credential deletion claims, rejects QR/replay/stale scopes,
and confirms the ledger remains unverified. Actual third-party erasure,
independent verification, retention policy and destructive connection
cleanup remain NOT_READY.

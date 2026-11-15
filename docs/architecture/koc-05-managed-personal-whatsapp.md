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


## Verification-readiness contract (KOC-05, v1)

The existing `PersonalConsentRecoveryService.list_retirement_evidence`
now owns a **version-fenced, transport-independent, read-only assessment**
of the authoritative owner-scoped SQL snapshot. The accompanying
`assess_retirement_evidence_snapshot` function is a pure interpretation
of stored evidence, not a second provider/verifier or a deletion authority.
The consent recovery service still independently enforces a freshly
verified principal, tenant isolation, `CHANNEL_CONSENT` RBAC,
`RuntimePolicy`, and `ActionExecutionGate`; it requires no live plugin,
provider credential, or ChannelHost. It fails closed on invalid evidence,
duplicate connection IDs, or an oversized result. The assessment cannot
create, mutate, erase, or unlock a connection.

Contract `retirement-verification-readiness-v1` returns
`status=blocked`, `cleanup_authorized=false`, and explicit,
code-stable blocking reasons. The local blockers reflect the immutable
retirement hold, enabled state, unrevoked consent, unresolved pairing,
missing vendor unlink claim, missing deletion request, missing
`provider_claimed` receipt, unverified deletion requests, unfinished
inbound work and unconfirmed outbound delivery. The SQL repository now
separately reports `credential_deletion_claim_recorded`, without leaking
provider receipt IDs or session references. These facts are **historical
snapshots**, not provider health or current proof of erasure.

Four mandatory independent blockers remain regardless of all local flags:
independent provider unlink verification, independent credential erasure
verification, scoped provider/backup retention review, and the absent
governed cleanup authority. A vendor receipt, a historical `verified`
label, an empty outbox, or all-local-success combination **cannot** clear
those requirements. Migration 51 continues to forbid promoting vendor
claims to `verified`.

The thin existing retirement evidence API is unchanged in location and
HTTP method; its validated response now includes the strict nested
`retirement_assessment`. Boolean success flags are typed as literal
`false`, the contract version is pinned, and invalid backend evidence
produces a redacted failure, not a fake verified state. Settings validates
the version, mandatory blockers, known codes and the immutable false
status, and renders explanations in the existing owner-only read-only
review. It never exposes a finalizer or cleanup button. No new endpoint,
database table, provider adapter, registry, or workflow is introduced.

Actual independently verified remote retirement remains **NOT_READY**.
It requires a separately governed, source-authenticated verifier with
vendor-specific trust and canonical tenant, owner, connection, provider,
session and revision correlation; signed/attested provenance and
tamper-evident retention; exhaustive credential, message, media, backup
and subcontractor retention policies; expiry and replay protection; and
a revision-fenced operator finalization protocol with explicit RBAC,
audit and rollback/unknown semantics. None of those are asserted or
fabricated by this report. Only after such proofs pass could a separately
reviewed contract evolve and enable specific cleanup operations.

Proof uses existing consent recovery policy/unit tests, schema/API
anti-forgery tests, frontend fail-closed contract tests, and the existing
disposable real PostgreSQL channel suite. It tests both incomplete
local evidence and a held connection with recorded original-session
unlink and credential deletion claims; both must remain blocked.
No external consumer packaging is required for these internal contracts.


## KOC-05 retirement claim correlation and outbound confirmation (v2)

The versioned owner-only retirement evidence contract is now
`retirement-verification-readiness-v2`. The canonical repository reports
`provider_revision_claims_correlated` only when **the same provider** has
a disconnected pairing observation with a nonempty unlink receipt and a
`provider_claimed` deletion record with a receipt, for the same tenant,
connection, owner and immutable original retirement-hold revision.
The hold must be active, the connection fenced and the current revision must
equal the hold's fenced revision. Separate existing flags still report whether
*any* provider unlink and credential-deletion claims were recorded. They do
not quietly disappear when a mismatched provider submitted one of them.

The source-assessment owner emits
`provider_revision_claims_mismatched` when both claims exist independently
but no same-provider, same-original-revision evidence pair exists. A
cryptographically authenticated provider callback and a scoped deletion
receipt are **claims**, not independent proof of remote unlink/erasure.
Provider/revision correlation is **not remote session correlation**: the
pairing ledger does not record a canonical verified remote session reference,
so even `provider_revision_claims_correlated=true` does not attest the same
remote session, credential destruction, complete retention scope or backup
deletion. The four independent-verification/finalization blockers remain
mandatory and cleanup authorization remains hardcoded false.

The owner evidence query also treats an outbox in `sent` state as
**unconfirmed provider delivery**. Only `delivered` or `read` status
excludes it from the outstanding-delivery blocker; such status remains merely
persisted provider evidence, not proof of remote message retention policy.
The v2 API has strict typed response fields and the UI rejects a v1 or forged
v2 status instead of presenting an invented retirement pass.

Regression proof remains in canonical tests and the disposable live
PostgreSQL channel suite. It stores a provider unlink for one provider and a
synthetic deletion claim for a different provider to prove mismatch detection,
then records the correctly scoped claim to prove correlation. It independently
checks that `sent` is still outstanding, all historical claims stay unverified
and owner/tenant isolation is preserved. There is no newly approved provider,
remote operation, cleanup permission, or additional orchestrator.

## KOC-05 nonblank provider receipt integrity (v2 read-side hardening)

The retirement inventory now treats a stored provider unlink or deletion claim
as present only if its provider receipt identifier contains non-whitespace
characters. The provider/revision correlation predicate applies the same
condition to **both** stored receipts. This is defensive for older or
privileged-imported evidence: the original pairing-state schema bounds receipt
length but does not prohibit an identifier containing only whitespace.
The credential-deletion schema already checks for nonblank receipt IDs; the
read-side guard applies consistently to both sources rather than assuming
historical data cannot be malformed.

The existing pairing reducer also rejects whitespace-only, oversized and
non-string provider receipt identifiers before storing link/unlink claims.
No provider callbacks are authenticated by this check, and no claim is
promoted to independent unlink or erasure proof. The v2 API shape, mandatory
verification blockers, owner/tenant scoping and `cleanup_authorized=false`
remain unchanged.

Canonical repository and reducer unit tests cover the SQL guards and the
invalid receipt transitions. The existing disposable PostgreSQL test stores
a valid original-revision claim, replaces the unlink receipt with historical
whitespace to prove it no longer counts, then restores the valid receipt and
proves that only local provider/revision correlation returns. Independent
session identity and credential/backup retention scope remain unverified.

## KOC-05 exact read-only blocker consistency (v2, no new authority)

The thin retirement-evidence API must reject an assessment whose claimed local
blockers disagree with the stored source flags, even if all four mandatory
independent-verification blockers are present. It now recomputes the expected
read-only assessment through the existing
`assess_retirement_evidence_snapshot` owner and requires an exact match to the
typed response, including local reasons and their canonical order. Evidence
booleans and connection revision use strict Pydantic types, so strings or
integer surrogates cannot become apparently valid flags.

The Channels Settings panel independently validates that each reported
local blocker matches the corresponding backend flag. It refuses stale,
missing, extra, contradictory, or reordered blockers rather than displaying
a misleading partly complete report. This validation never invents provider
health or erasure evidence, and it never constitutes deletion authority.
The `retirement-verification-readiness-v2` shape and all mandatory blockers
remain unchanged. A bad response is a redacted failure, not a partial success.

Existing API and frontend contract tests exercise every local flag, evidence
coercion, conflicting blocker lists and the unchanged legitimate blocked
report. Independent provider-session authentication, remote credential erasure
and retention/backup coverage are still unavailable. Finalization remains
disabled and requires its own security review.

## KOC-05 historical verified-label containment (v2, read-only)

The canonical `SqlChannelRepository.list_owned_personal_retirement_evidence`
reports `unverified_deletion_request=true` for **every retained credential
deletion request**, regardless of its historical `status` label. Previous
SQL used `d.status <> 'verified'`, which could have misrepresented an old
`verified` row as independently attested erasure even though this runtime
has no independently authenticated remote erasure verifier or provenance
ledger. The original immutable history is preserved: no rows are rewritten
or deleted, no triggers or tenant-RLS policy are bypassed.

Until a genuine source-authenticated verifier exists, the same owner-scoped
SQL observation reports request existence and unverified status together.
The pure `assess_retirement_evidence_snapshot` owner rejects contradictory
`deletion_request_recorded` / `unverified_deletion_request` values and any
credential-deletion claim without a recorded request. The strict API
re-evaluates that assessment; the Settings parser rejects an inconsistent
backend response rather than hiding the `credential_deletion_requests_unverified`
blocker. A connection with no deletion request still reports the missing
request blocker, not a fabricated pending request. The API shape and
`retirement-verification-readiness-v2` contract are unchanged.

This is intentionally conservative: a provider claim or a historical
`verified` status never establishes remote session identity, erasure,
retention/backup coverage or any final deletion permission. The
`cleanup_authorized=false` contract, four mandatory independent-proof
blockers, immutable retirement hold, tenant RBAC and audit constraints remain.

Existing canonical unit/API/Settings tests cover contradictory flags,
historical-status projection rules and no-request behavior; the existing
disposable live PostgreSQL suite continues to exercise real pending and
provider-claimed requests under tenant isolation, without disabling the
ledger integrity trigger or pretending a third-party verifier exists.

## KOC-05 canonical pairing reducer evidence freshness and type guards

The signed callback decoder already enforced HMAC integrity, strict JSON type
contracts, tenant/provider/connection scope and a five-minute observation age
window, but the canonical `apply_pairing_observation` reducer previously
accepted any truthy `authenticated` flag and typed Python dataclasses did not
perform runtime validation. Internal invocation with a correct sequence and
revision could also submit an arbitrarily old unlink observation.

The reducer now enforces strict native booleans for authentication and
approval flags, strict integer revision and sequence types (excluding bool),
actual `PairingEvent` values, timezone-aware timestamps and a
`PAIRING_EVIDENCE_MAX_AGE` of five minutes. The signed callback imports
this same age contract instead of maintaining an independent constant.
Malformed QR timestamps fail closed with a `PairingEvidenceDenied` error,
not an unhandled `AttributeError`/type error.

This is a **secondary validation boundary**, not an alternative callback
authentication path. HMAC source authentication, vetted installation lookup,
vault-resolved signing secrets, owner/tenant isolation, serializable revision
and sequence fencing, retired-session terminal-only transitions, and the
independent-erasure blockers remain in their existing owners. Local consent
revocation still allows timely authenticated teardown, without asserting
remote credential erasure.

Canonical unit tests cover truthy type coercions, exact five-minute edge
behavior, old QR/unlink observations, malformed timestamp data and legitimate
consent-revoked teardown. The existing real PostgreSQL integration now
attempts a stale, otherwise correct next-sequence disconnect and verifies the
stored pairing sequence cannot advance before continuing the valid teardown.
No provider was activated, no migration or new route added, and final
retirement cleanup remains unauthorized.

## KOC-05 disabled-connection pairing admission fence

`SqlChannelRepository.commit_personal_pairing_observation` is the
canonical transaction owner for admitted, provider-authenticated pairing
events. It already locks the owning connection, checks tenant/owner,
original revision, consent, stored event sequence and the irreversible
retirement hold. However, a **non-retired connection with
`enabled=false`** could previously accept `QR_ISSUED` or
`LINK_CONFIRMED` when the callback signature, consent, revision and
sequence otherwise matched.

The existing connection-row lock now also checks `enabled is True`
before allowing either pairing-establishment event. Thus a disabled
connection cannot mint a new QR observation or confirm a link, regardless
of a retained signing secret or active consent row. Terminal
`DISCONNECT_REQUESTED`, `UNLINK_CONFIRMED` and `FAILED` transitions
retain their established reducer, timestamp and sequence requirements,
so disabling a transport does not misrepresent a live remote session as
unlinked or trap timely authenticated teardown of a still-current
revision. Retirement holds continue to accept only original-revision
terminal evidence, as before.

The disposable live PostgreSQL channel suite now creates an owned,
non-retired disabled connection with an accepted consent row, proves
that a valid next-sequence QR cannot be stored, activates it through
`set_connection_enabled`, then explicitly simulates a legacy direct
SQL disable without revision change. A correctly scoped next-sequence
link receipt is rejected and the pairing row remains at the prior
`qr_available` sequence. This deliberately stronger test bypasses
the *test fixture's* normal revision bump, never the production
admission gate. It does not change any real provider configuration,
grant erasure authority, mutate historical retirement evidence,
introduce an endpoint or change the v2 report contract.

Independent vendor unlink/erasure verification and final destructive
cleanup remain unavailable.

## KOC-05 live owner status fence on pairing establishment

Initial personal connection ownership and risk consent require an active,
verified tenant user. However, a user's account can later become inactive
or unverified while the historical owner and consent rows remain. The
canonical `commit_personal_pairing_observation` previously checked
the owner's existence, but not the current `auth_users` status when
committing `QR_ISSUED` or `LINK_CONFIRMED`. An otherwise valid provider
signature, unrevoked consent and matching sequence/revision could therefore
create new pairing state on behalf of a former verified owner.

The existing repository now reads the tenant-matched owner's
`is_active` and `is_verified` flags in its connection-locked transaction,
using an additional `FOR SHARE OF u` lock to serialize concurrent account
status changes with pairing admission. Both flags must be exactly true for
QR or link confirmation, independent of a retained signing secret,
historic ownership and consent. The existing connection-enabled and
retirement-held gates, native source verification, strictly fresh reducer,
owner/tenant scoping and revision/sequence CAS remain in place.

The source-authenticated terminal transitions
`DISCONNECT_REQUESTED`, `UNLINK_CONFIRMED` and `FAILED` intentionally
remain available to an inactive or unverified historical owner when the
existing stored pairing and revision allow them. This prevents account
deactivation from falsely attesting remote unlink or stranding previously
linked sessions. No new account privilege is minted; a verified historical
owner row remains required for scope, and the reducer enforces the terminal
phase and fresh receipt requirements.

The disposable live PostgreSQL integration tests an account-deactivation
race behind an actual user-row `FOR UPDATE` lock, verifies that the
waiting QR observes the newly inactive state, and checks that both
inactive and unverified status block QR/link without advancing the
persisted sequence. After restoring live verification, normal pairing
succeeds; a later inactive owner can complete authenticated disconnect
and provider-unlink *claims* only. No real provider was enabled, and
none of this constitutes independently verified erasure or final cleanup.

## KOC-05 pairing status and inventory truth boundary

The current ChannelHost deliberately reports `live_connected=false` and
`qr_available=false` because no reviewed, current source-authenticated
remote session probe or QR retrieval capability is enabled. Only
`last_observed_phase` and a scoped `provider_unlinked` boolean represent
**historical provider claims**, not independently verified live state or
credential erasure. However, the prior API `PersonalPairingStatus` model
and settings inventory parser accepted arbitrary boolean `true` values
for the two unsupported capabilities. A stale/mock/malformed host result
could therefore display a fabricated live connection or QR.

The existing pairing status API and owner inventory now reuse one strict
`PersonalPairingStatus` contract: enumerated availability and persisted
phase, strict booleans, and a model-level prohibition on either live-health
or QR success until a separately authenticated source capability exists.
A persisted `provider_unlinked=true` is accepted only for a configured
provider whose last accepted phase is `disconnected`, without upgrading
it to independently verified unlink or credential deletion.

Both API responses validate the host output before serialization and
return a redacted HTTP 503 on contradictory or extra fields, rather than
silently converting a false source claim to success or disclosing vendor
receipt/session metadata. The Channels settings parser mirrors the
negative live-status invariants and rejects invalid phase/unlink
correlations, dropping the previous inventory on a failed refresh.
Regression tests cover forged booleans, numeric/string coercion, invented
phases, unsafe extra provider fields, post-refresh failure, and a
legitimate scoped historical unlink observation.

The response field names, consent/revocation actions, ownership,
tenant/RBAC enforcement, original-session retirement holds, and the
mandatory independent verification blockers are unchanged. This
validation does **not** implement remote session health, pairing QR,
device unlink verification, credential erasure or final cleanup.

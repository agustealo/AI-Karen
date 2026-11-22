# Document author consent: real browser acceptance

**Slice:** WS-04A9T through WS-04A9Y, PR #1183. This is a source-specific, first-party author workflow, not a generic chat approval or proof of third-party authorship.

## Execution authority

- The approved original is a **real existing** author-owned plain-text file, 1–65536 bytes, present in the canonical tenant-scoped PostgreSQL file registry. The approved writing-style profile must be a permitted draft.
- Only `ApprovalService` creates/decides document approval and issues consent through canonical `RuntimePolicyEnforcer` and `PostgresDocumentStyleConsentIssuer`. A browser button and chat metadata are not approval authorities.
- Receipt issuance consumes the approved request once, atomically with insertion and a locked canonical source check. The immutable consumed scope remains available for read-only recovery; recovered receipts are verified against current source SHA-256, permissions, revocation and expiry.
- The test does **not** upload a document, fabricate a consent receipt, or enable ingestion. Its opt-in mutation trial now creates its own pending approval through authenticated source initiation in the SAME live browser session used for confirmation.

## Real host trial, disabled by default

Run from `src/ui_launchers/Karen-AI-Theme` on an approved isolated test installation. Configure the following via a protected, non-logged environment, **never by committing credentials**:

| Variable | Required meaning |
| --- | --- |
| `KAREN_DOCUMENT_AUTHOR_ACCEPTANCE=true` | Opt in to read-only verification |
| `KAREN_BASE_URL` | Clean approved HTTPS origin, or explicit local loopback |
| `KAREN_LOCAL_CHAT_ACCEPTANCE=1` | Required only for a loopback host |
| `KAREN_UX_EMAIL`, `KAREN_UX_PASSWORD` | Real dedicated sanitized author account |
| `KAREN_DOCUMENT_AUTHOR_PROFILE_ID` | Real author-owned eligible draft profile UUID for the mutation trial |
| `KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID` | Expected canonical file UUID |
| `KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256` | Expected live file digest |
| `KAREN_DOCUMENT_AUTHOR_SOURCE_NAME` | Expected original filename |
| `KAREN_DOCUMENT_AUTHOR_MUTATION_ACCEPTANCE=true` | **Separate explicit permission** to confirm and issue a real receipt from the disposable fixture |

Run `npm run test:e2e:document-author`. Default opt-in performs **read-only** authenticated document inventory inspection without initiating an approval. The independent mutation gate uses a disposable, author-controlled source and profile to initiate a fresh approval in the same bearer session, verify the review's canonical identity, exercise explicit human confirmation, live issuance, page reload and receipt recovery. Real HTTP responses and actual credentials are used. There is no request interception, fixture mocking, trace, screenshot, video, JSON report or automatic retry. Authentication is origin locked and uses the existing approved-host login helper.

## Acceptance evidence and boundaries

Capture only sanitized job outcome, exact image/commit provenance, host identifier, test name, and whether the canonical receipt/SQL evidence is verified. Do not capture document text, passwords, bearer tokens, signed URLs, personal filenames, SHA-256 values, or raw session logs in CI artifacts.

A skipped opt-in test **does not count as passed live acceptance**. A green frontend unit or disposable PostgreSQL test **does not substitute** for production browser-to-PostgreSQL authorization. A mutation test should be run only with an intentionally disposable original and account, never a production user's document. Revocation must be tested separately before consumer activation.

Consumer ingestion and external Supabase Storage readiness remain **disabled / unverified** until signed storage, target-host authentication, source provenance, revocation, and observed browser acceptance are all satisfied. External dependencies do not stop internal implementation, but they remain release gates.


## WS-04A9U: source initiation and adversarial live acceptance gates

**Exact-source evidence required:** A source uploaded or selected through the existing authenticated runtime must have its identity verified from the canonical `files` row, not browser-supplied metadata. The present browser suite starts from a pre-existing disposable author-owned approval and therefore **does not prove source initiation**.

**Existing storage capability:** `ArtifactStore.read_owner_active_text_bounded` is a fail-closed interface. `SupabaseArtifactStore.read_owner_active_text_bounded` implements a pinned, ranged, streaming read that verifies owner, deletion status, MIME, byte limit, storage path, response range, actual byte count and SHA-256. This is a transport and integrity capability, **not** evidence of authorship or permission to analyze or use a writing style. No consumer document ingestion path should be enabled on this basis.

### Acceptance matrix (all rows require observed evidence)

| Gate | Observable proof | Required denial |
| --- | --- | --- |
| Authenticated author initiation | Dedicated author creates/selects an actual permissible artifact through existing runtime ownership, then a pending approval with the exact source fingerprint is recorded by `ApprovalService` | Browser-supplied author identity, document digest, purposes or policy decision must not create an approval |
| Consent review | Current bearer and original tenant/actor/session agree with persisted scope; source filename, size, MIME and SHA-256 are read from canonical storage metadata | Different author, tenant, session, modified or deleted source, revoked session and expired approval |
| Explicit confirmation | The first-party checkbox gates a real author decision with current `RuntimePolicy`; consent is not inferred from viewing or from the chat/model | No checkbox gesture, chat approval replay, copied policy decision ID or generic approval action |
| Atomic receipt issuance | One consumed approval and one receipt are recorded in the same PostgreSQL transaction against the locked source and current bearer | Competing issuers, stale authorization, changed source or already-consumed mismatched scope |
| Lost-response recovery | Reload and retry return the **same** currently valid receipt ID from durable PostgreSQL evidence, without inserting another receipt | Revoked/expired receipt, purpose drift, source drift or foreign bearer |
| Revocation after issuance | Revoking via currently authorized author path fences both draft and published profile use; current source checks and delegated requests deny use | A copied receipt, stale sample metadata or direct-SQL grant cannot re-enable use |
| Supabase content read | On a real approved target host, observe the canonical transport-bounded source-owner read with verified hash and no leaked content/token logs | Missing 206/Content-Range, redirect, oversized response, unexpected path/host, digest mismatch or storage failure |
| Consumer runtime use | Existing persisted sample authority and KariSignature purpose checks revalidate live source/consent eligibility before publication and every use | Disabled/missing source authorizer or revoked permission fails closed |

### Separation of automated and external evidence

The current Playwright tests cover review UI gating and optional real receipt issuance/recovery **only when explicitly opted in and run with real sanitized fixtures**. The existing disposable PostgreSQL proof exercises selected authorization, rollback and revocation guarantees. Neither test family alone certifies every row above.

To complete WS-04A9U without introducing duplicate owners:

1. Extend the **existing** disposable PostgreSQL and host-author acceptance tests with rejected revoked bearer, expired approval/receipt and concurrent issuance. Assertions must check durable row counts and denial, not merely HTTP status.
2. Verify the current source-initiation ingress and `ApprovalService` call path using actual authenticated runtime composition. Only add a thin adapter when the canonical owner contract is independently proven.
3. Run the live browser trial against a dedicated isolated author account and explicitly disposable source, then independently prove the source read and revocation/use boundaries.
4. Record exact commit, approved-host identity, sanitized pass/fail artifacts and independent review on this PR. A skipped test, mock or prior-head CI result must not be promoted to release acceptance.

**Release invariant:** Keep PR #1183 draft, consumer writing-style document ingestion disabled, and source-family availability fail-closed until every required live authorization, storage and publication/use gate has observed evidence.


### WS-04A9V: PostgreSQL negative/concurrency regression (pending exact-head CI)

The existing disposable `test_first_party_author_consent_postgres` now asserts that an expired persisted approval cannot be consumed even with a matching author/tenant/scope; its row remains `approved` until a valid expiration is restored. The real issuer is then invoked simultaneously twice against the same valid author-confirmed approval through two PostgreSQL transactions. Acceptance requires exactly one non-null issuance result, one denied attempt, exactly one committed document-consent receipt, one consumed approval, and the original durable document scope retained for readback. This tests the existing SQL CAS and issuer together; it does not add an alternate locking coordinator or API flow.

These checks are **code committed but not yet independently passing** until fresh KariSignature PostgreSQL CI and all other required exact-head workflows succeed. Source initiation from an authenticated browser, the dedicated target-host trial, session-revocation browser observability, and real Supabase Storage approval remain unverified external/end-to-end gates. Keep consumer ingestion disabled.


### WS-04A9W: authenticated source-bound initiation (API foundation)

A new **first-party, non-ingesting initiation** endpoint is available at `POST /api/approvals/document-consent/initiate`. Its strictly validated input contains only `profile_id`, `artifact_id`, and the requested Boolean `style_use_allowed`. The endpoint deliberately rejects additional keys, including caller-selected tenant, actor, session, SHA-256, consent duration, policy decision and analysis grant.

The existing `ApprovalService.initiate_document_consent` validates a fresh high-risk author bearer, resolves the authenticated tenant/actor/session, reads the current plain-text digest from the canonical `files`/draft-profile owner under PostgreSQL scope, constructs the immutable scope with `analysis_allowed=true` and a server-limited one-day expiration, and delegates to `request_document_consent`. The latter independently revalidates the session, source and RuntimePolicy, then persists a **pending**, high-risk approval. It never confirms authorship or issues a receipt. Explicit author confirmation and the original atomic receipt issuer remain separate steps.

The HTTP and service regressions assert strict rejection of authority-field injection, non-Boolean use selection, missing source, malformed IDs and no issuance before the author gesture. These tests are committed but require fresh exact-head CI. This foundation is **not** yet a consumer file-selection UI, does not prove a live host end-to-end browser initiation, does not read the document's text into a model and does not enable writing-style ingestion. A dedicated browser trial must still prove source initiation against actual identity/authorization and consent receipt/revocation evidence.


### WS-04A9X: author-controlled document selection and pending-review browser gate

The author initiation page at `/approvals/document-consent/new` reuses authenticated owner metadata from the existing `GET /api/artifacts/` ingress. It only offers active plain-text `attachment` or `document` metadata with a canonical UUID, valid source digest and a 1–65536-byte size. Local filtering is **presentation only**; the pending-approval owner still checks the currently authenticated author/tenant, draft profile and canonical source digest under PostgreSQL lock. Unsupported or unavailable inventories do not fall back to arbitrary document IDs.

The page requires an explicit existing draft-profile UUID because no verified author-scoped profile picker is connected in this slice. This field is only a selector, **not** authorization. The submission sends exactly `profile_id`, `artifact_id` and the requested Boolean `style_use_allowed`; the backend independently derives the principal/session and source digest. Only a real `pending` document approval response may navigate the browser to the existing dedicated author confirmation screen. A failed/uncertain response does not claim that consent was granted. No document bytes enter the page or its request.

The existing real-browser acceptance suite now includes a **separate opt-in mutation-gated initiation** test: the author logs into the approved origin, selects the exact owner-listed source, requests a pending approval, and verifies canonical source identity on the dedicated confirmation page while the confirmation checkbox remains unselected and the confirm action disabled. Set `KAREN_DOCUMENT_AUTHOR_PROFILE_ID` to the real author-owned eligible draft profile UUID in the same protected, non-logged environment as the existing test fixtures. A skipped test or missing profile fixture is not acceptance evidence.

This is the **first-party source-selection and pending-approval UX**, not completed browser-to-PostgreSQL certification, a profile-discovery UI, document-text ingestion, publication, or use authorization. Consumer document ingestion remains disabled. Fresh exact-head frontend and PostgreSQL checks, independently observed host trial, signed storage read and revocation/use proof are release requirements.


### WS-04A9Y: canonical draft-profile inventory and P2 browser repairs

The first-party selector now lists only author-owned draft profiles from `WritingStyleProfileRepository.list_owned_drafts`, invoked by `ApprovalService.list_document_author_draft_profiles` after fresh high-risk bearer validation and exposed through the thin `GET /api/approvals/document-consent/profiles` route. The SQL query scopes tenant and owner, requires `state='draft'` and `publication_revision=0`, and runs under existing RLS. The browser does **not** accept free-form profile IDs or infer eligibility from displayed records. Initiation performs its own authorization and locked source verification.

The live-browser suite no longer attempts to review approvals created under an unrelated login token, which would correctly fail the server's session binding. The read-only trial checks only the authenticated source inventory. The explicitly authorized mutation trial initiates a new approval in its live author session, checks the pending state before confirmation, then verifies receipt issuance and durable readback. Both source and profile selectors must return the dedicated fixture; missing inventory is denial, not permission to type an ID.

Playwright now polls the actual canonical review values after the asynchronous preview request instead of asserting immediately after the section container appears. No sensitive source IDs, filenames, digests or auth tokens are placed in assertion error messages or artifacts. The review fixes do not weaken the runtime approval session binding, nor do they certify a live trial until executed on a target host.

**Remaining:** complete fresh exact-head CI and independent review, observe the real approved-host browser trial and Supabase storage proof, verify current source consent through publication and every delegated use. Keep draft/unmerged and consumer ingestion disabled.


### WS-04A9Z: author revocation after durable issuance

Once a current issued consent receipt is verified, the dedicated author screen offers a separate, unchecked **Revoke document consent** gesture. It sends only `{"confirmed":true}` to the strict first-party `POST /api/approvals/document-consent/{approval_id}/revoke` endpoint. The endpoint rejects any caller-supplied tenant, actor, artifact, profile or receipt scope. The existing ApprovalService recovers the durable approval scope and verifies that a currently live, source-matching consent receipt is present; only then does the existing RuntimePolicy-authorized SQL issuer perform its one-way revocation. Success is returned **only after the backend confirms revocation**. Failed or uncertain revocations do not claim success in the browser.

The opt-in live mutation acceptance now covers creation, human confirmation, issuance, reload/receipt recovery, explicit revocation, and absence of a recoverable receipt after another reload within the SAME authenticated session. Read-only acceptance remains nonmutating. The disposable PostgreSQL acceptance continues to prove that revoked document consent permanently revokes the published profile and delegated grants; direct SQL un-revocation is denied. No model inference, document ingestion, publication, or delegated action is enabled in this slice.

**CI status:** 19/19 passed for preceding `fd7b9072ab5fe0db8201e2221a32c7db6a58bed9`. The new WS-04A9Z revocation head has separate exact-head checks that must pass before this implementation can be considered validated. Live browser and storage proof remain external go/no-go gates, and consumer ingestion stays disabled.


### WS-04A9AA: delegated-use runtime denial regression

The disposable PostgreSQL acceptance now invokes the existing `WritingStyleProfileRepository.read_current_published` and `authorize_use` owners **after** author consent has been revoked and its database trigger has revoked the published profile and delegate grant. Both methods must deny access to the previously authorized delegated actor even when that caller retains a historical published revision ID, revision number and digest. This is a runtime-query regression rather than a frontend visual assertion, a simulated grant or a new authorization helper.

The preceding `fd7b9072ab5fe0db8201e2221a32c7db6a58bed9` head passed 19/19 workflows; its two P2 browser review threads were resolved after evidence-backed fixes. The revocation and delegated-use changes require their OWN exact-head tests and live-host acceptance before release. No actual target-host execution, Supabase Storage read or consumer ingestion is claimed by this source test.


### WS-04A9AB: uncertain revocation response recovery

When the revocation HTTP response is lost or fails, the first-party author screen now reads the existing server-verified current receipt endpoint before displaying a continuing receipt. If a current receipt remains, it displays a non-success warning and preserves the verified receipt. If no current receipt can be verified, it removes the stale identifier without claiming the revocation succeeded. This also preserves the strict distinction between `revoked` finality, `current receipt` verification and `unknown` outcome. Frontend regression tests cover both outcomes.


### WS-04A9AC: reconciliation with live main and certification policy

The PR branch is reconciled with mainline commit `119a36904951e2819bcb097a6e3d9bb1aa1b7817` through a true two-parent commit. The existing seven forensic-browser and architecture files are preserved byte-for-byte from main; the web package retains BOTH the mainline `test:e2e:chat-live` and the PR's `test:e2e:document-author` commands. Branch comparison confirmed no missing mainline commits after reconciliation.

This integration does not substitute for an exact-head CI run. If the source branch is in draft state and workflows do not start, mark it reviewable solely to trigger the required pull-request synchronization checks, then return it to draft before any merge. No consent, writing-style ingestion, deployment or training capability is enabled by this reconciliation. Release stays blocked until fresh checks and all target-host/storage evidence are verified.


### WS-04A9AD/AE: fresh-token, archived-source author revocation

Independent review found two fail-closed mistakes in the revocation UX: a refreshed author bearer could not match the originating one-time approval token, and a deleted/archived source prevented a still-persisted receipt from being revoked. Both are distinct from source-bound issuance.

The approval loader now has a **private** original-session control. Review, author confirmation and receipt issuance continue to require the original session. Revocation instead loads the consumed approval with a fresh, authenticated bearer matching the durable author and tenant, verifies the canonical approval fingerprint and policy decision, and relies on the existing RuntimePolicy plus one-way PostgreSQL revocation issuer. The revocation SQL further binds the original source SHA-256 from the stored approval; it does not require the document to exist or be currently readable.

A new author-only `GET /api/approvals/document-consent/{approval_id}/revoke-review` returns minimal durable provenance, not source bytes or a claim that consent remains live. If the original-session preview fails after token refresh or source deletion, the existing review screen can obtain this verified fallback and offer an explicit second revocation gesture. A successful response is claimed only after SQL confirms a one-way transition. The revocation POST explicitly requires `confirmed: true` **at ingress and inside ApprovalService**.

The disposable PostgreSQL test revokes a receipt after the file is marked deleted and rejects a forged source digest, then checks the profile and delegated-use fences. The opt-in browser mutation trial uses a fresh browser context and a new login for revocation after issuing/recovering consent with the original author session. No test bypasses identity or session validation.

**Observed regression:** first post-reconciliation exact-head KariSignature CI reported 218 passed, 1 failed on an HTTP boundary test that showed `confirmed: false` was accepted by a mocked service. Ingress now rejects it independently. This revised head must be revalidated; previous green runs cannot certify it. Live host, storage and consumer-ingestion acceptance remain held.


### WS-04A9AH: source-owner inventory reuses canonical bounded pagination

The first-party source picker no longer requests the tenant-wide `GET /api/artifacts/` inventory, which previously loaded every tenant artifact before the HTTP controller filtered by the current user. It now calls `GET /api/artifacts/owner-page?limit=100`, backed by the existing `ArtifactStore.list_owner_artifacts_page` contract and `SupabaseArtifactStore`'s tenant-and-owner-scoped keyset PostgreSQL query. The new thin route returns only source metadata, a scoped opaque cursor and `has_more`; it does not return object storage locations or source bytes. A broken cursor, missing owner scope, inconsistent row owner or repository failure denies the page.

A **Load more owned documents** control fetches successive pages. The UI still filters to active, correctly hashed, bounded plain-text candidates and lists only server-returned IDs. A source selected through the browser grants no consent or document read: `ApprovalService` and the PostgreSQL source owner recheck the original actor, tenant, exact digest and draft-profile scope at initiation and issuance. The real-browser fixture walks bounded pages rather than assuming its dedicated source appears in the first 100 rows.

HTTP and component tests cover owner/tenant binding, pagination, malformed cursors, invalid limits, foreign source rows, malformed pages and page-two source selection. The source table remains `public.files` throughout; no parallel registry, plugin authority or storage adapter is introduced.

**Release:** Passing exact-head CI is separate from approved-host acceptance. The complete 19/19 green prior head was `8ef95ab8997a17ebaeb418e6a4572a8d27936648`. This owner-pagination change requires its own fresh exact-head checks. Consumer ingestion remains disabled until authorized browser-to-storage source read and revocation behavior are observed on the target host.


### WS-04A9AJ: exact-head evidence for owned-source discovery

The existing `KariSignature PostgreSQL Principal and Revocation Proof` workflow now explicitly compiles and runs the source-owner HTTP regression suite `tests/api_routes/test_document_author_owned_artifacts_http.py` alongside the consent HTTP and PostgreSQL tests. Its existing branch path filters include the owner endpoint and canonical ArtifactStore adapter so changes to their authority cannot silently bypass this dedicated source-consent proof.

The first owner-pagination head's `Web pnpm 11 Build Proof` failed on a malformed **test fixture** in the empty-draft-inventory case. The revised fixture returns the complete paginated metadata shape and no longer has the parser error. This latest head must independently pass CI. A test status on an older head is not accepted as proof for the revised branch.

# Document author consent: real browser acceptance

## Current release truth (supersedes historical draft checkpoints)

**Source integration: MERGED.** WS-04A9's source implementation merged from PR #1183 to `main` at `aadd12579351962229b18ce6b90a0b3a8891715d`. Earlier statements in the dated WS-04A9 development notes about keeping **that PR draft or unmerged** describe their historical checkpoints only; they are no longer an instruction to roll back the completed merge or to block unrelated development.

**Consumer capability: HOLD.** The merged source does not activate writing-style document ingestion and is not certified as consumer-ready. The approved-host author browser flow, real bounded Supabase Storage read, and two-phase delegated-use revocation evidence remain unverified. A completed GitHub workflow, an available Vercel frontend, or a skipped opt-in acceptance test is not a substitute for their observed deployment results.

**Canonical local acceptance record:** [PR #1183 local acceptance handoff](https://github.com/agustealo/AI-Karen/pull/1183#issuecomment-7089515191). GitHub Issues is disabled in this repository, so keep sanitized acceptance results linked to that existing record. External-host setup and disposable fixture preparation may proceed locally and do not hold subsequent internal green PRs. **Do not enable ingestion or claim live acceptance until the remaining gates are observed.**


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


### WS-04A9AK: bounded-inventory live acceptance and CI collection repair

The first owner-page integration head `665655b108e6696c1ff29f9164862f0e55c3d05a` exposed two independently actionable issues. The KariSignature PostgreSQL proof was blocked at **HTTP-test collection**, because importing the existing artifact upload router requires `python-multipart` even when the requested test covers only owner metadata. Its dedicated CI dependency installation now includes multipart; no production database permission or artifact authorization behavior is changed.

The inline review also found that Playwright's source selector could mistake an as-yet-unloaded document inventory for an empty page. It now waits for the initial loading indicator to disappear and refuses an error alert before interpreting an absent source dropdown or pagination control. Later-page source selection still uses owner-keyset pages and never a free-form document identifier.

These repairs need their own exact-head CI and independent live-target-host author acceptance. They do not activate ingestion, add a storage backend or authorize document content use.


### WS-04A9AQ: later-page live browser response synchronization

A P2 review of the reconciled head identified a further acceptance-only race. A paginated source button changes its accessible name from `Load more owned documents` to `Loading documents…` as the request is pending, which makes a negated assertion against the first locator succeed prematurely. The Playwright source selector now attaches a response waiter to the real `GET /api/artifacts/owner-page` cursor request *before clicking*, requires a successful HTTP response, then waits for the loading button to disappear and the author inventory to remain free of error alerts before examining the next page's options. It does not use request interception, an alternate artifact ID input, or mutate approvals. The production source-picker and consent authorization paths are unchanged.

The fix requires fresh exact-head CI; this is **not** proof that the opt-in real-host Playwright acceptance suite ran. Independent approved-host and storage evidence remains required.


### WS-04A9 development hardening: owner-page repository contract

The existing authenticated `GET /api/artifacts/owner-page` boundary now rejects malformed canonical repository responses rather than silently returning an apparently complete inventory. In particular, it requires a list no longer than the requested page size, an explicit Boolean `has_more`, a bounded non-repeating cursor on a nonempty continuation page, and no unexpected cursor on a final page. The source registry remains `public.files` and the query remains tenant-and-owner scoped; no document bytes or browser-provided authorization are admitted.

The focused HTTP regression covers missing/string page flags, missing/oversized/repeated cursors, empty continuation pages, over-limit pages and invalid result payloads. **Development-gate note:** this source and regression update is committed but has not yet received targeted exact-head test execution. Do not inherit the prior 19/19 green result for this changed route. In accordance with the slice's development-stage CI policy, do not trigger unrelated full-matrix builds solely for this step; the dedicated KariSignature PostgreSQL owner HTTP test is the relevant next proof. Host/browser and real-storage release acceptance remain separate and unverified.


### WS-04A9: bound source-picker filenames to canonical reader eligibility

The author-facing owner inventory now filters document filenames to the **existing** `SupabaseArtifactStore.read_owner_active_text_bounded` basename contract: a 1–160 character ASCII safe basename beginning with an alphanumeric character, with a `.txt` or `.md` extension (case insensitive), and without path separators. Previously, any nonempty name could be selected despite being rejected by that canonical reader. The UI also ignores malformed null inventory entries rather than throwing while rendering. Component regression cases include safe Markdown, spaces, traversal paths, unsupported extensions, nested paths and overlong filenames.

This is a **presentation eligibility guard**, not an authorization mechanism. The server still derives actor, tenant, session, canonical digest and consent permissions, and real Supabase Storage reads still need independently observed target-host evidence. Development-stage focused frontend tests are required for the changed head; the previous exact-head security proof covers the unchanged backend only. No full-matrix rerun or mainline reconciliation is required merely for this picker change.


### WS-04A9: non-vacuous live receipt-revocation denial

The existing opt-in, mutation-gated browser acceptance now verifies the **same authenticated original bearer** on both sides of revocation: its canonical receipt recovery endpoint must return **HTTP 200** immediately after issuance and reload, then **HTTP 403 or 404** after the author revokes from a freshly logged-in, separate browser context. This verifies a real server-side denial, not merely that the receipt has disappeared from the UI. The browser-only status probe reads its own authentication token internally and returns **only the numeric status** to the test runner; it never exports bearer credentials, document contents, receipt JSON or signed URLs. Screenshots, traces and videos remain disabled.

This new assertion requires explicit `KAREN_DOCUMENT_AUTHOR_MUTATION_ACCEPTANCE=true` and an approved disposable author fixture on the target host. A CI build or skipped Playwright test is **not** evidence that the live scenario ran. The assertion proves receipt recovery is fenced after revocation; **delegated writing-style use denial still requires independent runtime evidence**, and actual Supabase Storage bounded reads remain a separate release gate. Consumer ingestion remains OFF until real-host acceptance; the original draft PR requirement is superseded by the completed merge described above.


### WS-04A9 live storage-read probe (read-only, opt-in)

The repository now includes `tests/integration/test_document_author_storage_live.py`, an independent **real-host**, read-only acceptance probe using the existing `DatabaseServiceFactory` and canonical `SupabaseArtifactStore.read_owner_active_text_bounded`. It does **not** construct a new storage client, bypass the artifact owner, fetch an unsigned URL or read a mocked response.

Run it **inside the approved isolated target installation**, with actual PostgreSQL and Supabase Storage connectivity and a pre-existing disposable text artifact. Supply these values in a protected, non-logged environment:

| Variable | Value |
| --- | --- |
| `KAREN_DOCUMENT_STORAGE_LIVE_ACCEPTANCE=true` | Explicitly enable real storage acceptance |
| `KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID` | Canonical UUID for the existing disposable `files` row and storage object |
| `KAREN_DOCUMENT_AUTHOR_TENANT_ID` | Canonical UUID of its authenticated tenant |
| `KAREN_DOCUMENT_AUTHOR_USER_ID` | Canonical UUID of its authenticated owner |
| `KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256` | Expected lowercase SHA-256 of exact stored UTF-8 source bytes |

Use `PYTHONPATH=src python -m pytest -q -s tests/integration/test_document_author_storage_live.py` in the approved host runtime. This is *not* a CI release step by default. If the opt-in flag is absent, pytest skips; skipped acceptance is **not a pass**. If opted in with missing fixture data, unavailable storage, absent 206/Content-Range semantics, an invalid digest or wrong-principal data leak, the test fails. It verifies current source bytes using the canonical owner's already bounded streaming and digest-checking path, rejects wrong-tenant and wrong-owner access using actual repository calls, and emits only sanitized read duration and byte count through structured logging. Do not publish source text, tokens, object URLs, fixture IDs or SQL rows to test artifacts.

The test proves **storage availability, bounded integrity and owner isolation at the tested installation and time** only. It does not establish first-party authorship, receipt issuance, later runtime delegated-use revocation, or consumer readiness. Run the separately opt-in authenticated Playwright consent/revoke trial, and obtain fresh runtime-owned delegated-use denial evidence before lifting the release hold.

**Execution status:** added to source; **no approved target-host execution or result is claimed**. Do not automatically turn this test on in ordinary PR CI or infer that previous PostgreSQL integration tests ran against real external Supabase Storage.


### WS-04A9: live delegated-use two-phase acceptance

`tests/integration/test_document_author_delegated_use_live.py` is an **opt-in, read-only** probe against the existing `WritingStyleProfileRepository` and `KariSignatureResolver`. It checks that an actual published revision and delegated-purpose grant work **before** the author revokes, and that the same revision is inaccessible and its resolver rejects **after** that revocation. The probe never creates profiles, grants, revocations, receipts, fake SQL rows or model responses.

On an explicitly approved isolated host, prepare a genuinely delegated, published, disposable author-owned style that references a live issued document-consent receipt. Provide protected, non-logged environment values:

| Variable | Required value |
| --- | --- |
| `KAREN_DOCUMENT_DELEGATED_USE_LIVE_ACCEPTANCE=true` | Opt in (absent means **skip**, not pass) |
| `KAREN_DOCUMENT_DELEGATED_USE_PHASE=before` / `after` | Explicit phase; neither is inferred |
| `KAREN_DOCUMENT_AUTHOR_TENANT_ID` | Canonical UUID for the approved tenant |
| `KAREN_DOCUMENT_AUTHOR_PROFILE_ID` | Canonical UUID of the same published style profile |
| `KAREN_DOCUMENT_DELEGATE_USER_ID` | Canonical UUID of the actual preauthorized delegate |
| `KAREN_DOCUMENT_PUBLISHED_REVISION_ID` | Existing published revision UUID, retained for the after phase |
| `KAREN_DOCUMENT_PUBLISHED_REVISION_NUMBER` | Matching positive canonical revision number |
| `KAREN_DOCUMENT_PUBLISHED_REVISION_SHA256` | Lowercase SHA-256 digest of the canonical approved expression |
| `KAREN_DOCUMENT_PUBLISHED_EXPRESSION_JSON` | The matching approved expression JSON; no source document content |
| `KAREN_DOCUMENT_DELEGATED_PURPOSE` | Actual granted use, e.g. `draft_email` |

First execute `PYTHONPATH=src python -m pytest -q tests/integration/test_document_author_delegated_use_live.py` in phase **before**. It must observe the real current published revision, authorize the known revision and resolve the style through `KariSignatureResolver`. Only after a successful positive phase, revoke **that same document consent** using the existing authenticated author flow and independently verify the revocation. Execute the unchanged fixture in phase **after**. It must observe no current published revision, reject authorization of the known former revision, and raise `style_unavailable` through the canonical resolver.

Retain sanitized evidence of both phases, the distinct author revocation transaction, the same approved host/database/tenant/profile/revision provenance, and the actual commit. An **after-only negative** is vacuous and **does not count** as acceptance. A skipped run, simulation or unit test also does not qualify. Timing is observed, not a promised SLO. No source bytes, credentials, original author document or bearer credentials should enter artifacts.

**Current status:** the acceptance source is merged, but neither phase has executed on an approved host and no real delegated grant has been created or revoked by this change. Consumer ingestion remains OFF and the **consumer capability** stays on HOLD. Historical draft-PR wording above does not apply to the merged source.


### WS-04A9 live probe evidence-quality refinements

The opt-in delegated-use probe now accepts any purpose valid under the existing `KariSignatureRequest` contract. It does not maintain a second hardcoded purpose registry. The real scoped PostgreSQL grant and the canonical resolver decide whether a particular purpose is allowed. Its measured duration includes the entire read, authorization, and positive/negative resolver path, not just the earlier preliminary checks.

The bounded Supabase Storage probe also makes a **second read request using the same real owner/artifact but an undersized maximum-byte budget**; it must be denied and must return no text. This is distinct from the cross-tenant and cross-owner denials and does not replace the canonical storage owner's pre-transfer length, 206 range, and digest controls.

Neither probe has executed against an approved target installation. These refinements supply stronger requirements for the future host trial, **not** evidence that the host passed them. Keep all live-gate statuses unverified until observed.


## WS-04B0: governed document content-reader composition (development only)

The canonical `ArtifactStore` now provides `read_owner_active_text_bounded`, so `ArtifactWritingStyleContentReader` in the existing document-source authority module adapts this **already-owned** capability for the `WritingStylePersistedSampleAuthority` reader protocol. No second storage client, download fallback, independent content cache, user-supplied URL or new authorization engine is created.

The reader accepts only canonical tenant/actor/document UUID scope, delegates an explicit 65,536-byte budget to the existing storage owner, and accepts only a typed `VerifiedArtifactText` matching the requested tenant, actor, artifact, safe text filename and MIME. Unsupported sources, invalid scope, denied or unbounded storage, mismatched output and errors return no content.

**Crucially, reading bytes is not itself permission to learn or imitate an author.** The surrounding persisted-sample authority continues to validate the profile-specific consent receipt and current PostgreSQL evidence before and after the source read, including the exact content digest; RuntimePolicy remains responsible for execution. This adapter is not auto-registered for consumer document ingestion and does not enable the feature.

Focused source-owner unit tests exercise canonical bounded-call delegation, malformed scopes, cross-owner/tenant data, unsupported types, storage denial and exceptions. Real Supabase transport integrity and browser-to-consent revocation remain local acceptance requirements under the existing handoff; they are not inferred from tests.

### WS-04B2: approval-scoped UI state and delayed-response fencing

The first-party document author confirmation component now creates a fresh, keyed
screen instance for each canonical approval ID. A late receipt/confirmation
response for a previously viewed approval cannot populate the new review. The
existing receipt owner remains authoritative: in-flight receipt reads are
invalidated when revocation begins, after an issued receipt is requested, and
when the screen unmounts. A delayed prior confirmation cannot trigger a second
receipt-issuance call after the author navigates to a different approval.

Frontend regressions cover out-of-order receipt recovery, revocation winning
over a stale read, and a late previous-approval confirmation. This is a
**presentation and action-continuation integrity fix**, not a new consent
issuer, a proof of host activation, or authorization to ingest documents.
Consumer ingestion remains OFF until independent real-host author, Supabase
Storage and delegated-use acceptance are observed.

### WS-04B3: consent recheck after source-derived style analysis (internal only)

The existing `KariSignatureSampleAnalyzer` now reuses the *same* trusted
`WritingStylePersistedSampleAuthority` immediately before returning any
heuristic proposal, including `insufficient_evidence`. A positive preflight
authorization is not a consent lease. This second authorization repeats the
source-specific, profile-specific receipt, owner, bounded source-byte and
PostgreSQL sample-evidence checks. If consent or evidence is revoked while the
heuristic runs, or the storage/issuer becomes unavailable, the proposal is
discarded with the same redacted `style_sample_unavailable` failure. It is
still unapproved, contains no source text and grants no publication or use.

The existing independent PostgreSQL profile lifecycle and grants remain the
owners of publication and delegated-use decisions. Source-only tests and the
canonical KariSignature PostgreSQL proof now cover the post-heuristic boundary;
this is not evidence of a real-host analysis, a production runtime registration,
or consumer activation. The two checks are separate observations rather than
an atomic snapshot of external storage and consent. The current release HOLD
remains until the approved-host author, bounded Supabase Storage, and delegated-
use before/after acceptance are observed.

### WS-04B4: canonical artifact tenant type alignment

An adversarial schema audit found that the canonical `public.files.tenant_id`
column is `TEXT`, but writing-style document consent and profile tenant
identifiers are `UUID`. The prior issuer queries, grant-time document check
and consent INSERT trigger compared these types without a cast. Test fixtures
had independently defined `files.tenant_id UUID`, masking the defect.

The additive `69_writing_style_document_file_tenant_text` migration replaces
only the existing consent validation function, comparing the authenticated
receipt tenant UUID as text against the unchanged canonical file tenant text.
The runtime issuer, review source summary, current receipt verifier, and
profile grant preflight use the same canonical direction. No arbitrary file
metadata is cast to UUID, no document bytes are exposed, and the existing
owner, digest, deleted-state, bounded-size, attestation, immutable receipt and
revocation requirements remain in place. The old migration is not rewritten.

Disposable PostgreSQL fixtures and a source-schema regression now use the
production `TEXT` column and apply the forward migration. This is an
internal eligibility/SQL correctness repair, **not** a document-ingestion
activation or approved-host acceptance result. The separate author, storage,
browser and delegated-use live acceptance HOLD remains.

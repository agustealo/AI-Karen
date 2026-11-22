# Document author consent: real browser acceptance

**Slice:** WS-04A9T, PR #1183. This is a source-specific, first-party author workflow, not a generic chat approval or proof of third-party authorship.

## Execution authority

- The approved original is a **real existing** author-owned plain-text file, 1–65536 bytes, present in the canonical tenant-scoped PostgreSQL file registry. The approved writing-style profile must be a permitted draft.
- Only `ApprovalService` creates/decides document approval and issues consent through canonical `RuntimePolicyEnforcer` and `PostgresDocumentStyleConsentIssuer`. A browser button and chat metadata are not approval authorities.
- Receipt issuance consumes the approved request once, atomically with insertion and a locked canonical source check. The immutable consumed scope remains available for read-only recovery; recovered receipts are verified against current source SHA-256, permissions, revocation and expiry.
- The test does **not** upload a document, create an approval, fabricate a consent receipt, or enable ingestion. Source initiation must be independently verified through canonical runtime owners.

## Real host trial, disabled by default

Run from `src/ui_launchers/Karen-AI-Theme` on an approved isolated test installation. Configure the following via a protected, non-logged environment, **never by committing credentials**:

| Variable | Required meaning |
| --- | --- |
| `KAREN_DOCUMENT_AUTHOR_ACCEPTANCE=true` | Opt in to read-only verification |
| `KAREN_BASE_URL` | Clean approved HTTPS origin, or explicit local loopback |
| `KAREN_LOCAL_CHAT_ACCEPTANCE=1` | Required only for a loopback host |
| `KAREN_UX_EMAIL`, `KAREN_UX_PASSWORD` | Real dedicated sanitized author account |
| `KAREN_DOCUMENT_AUTHOR_APPROVAL_ID` | Existing real author-scope approval UUID |
| `KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID` | Expected canonical file UUID |
| `KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256` | Expected live file digest |
| `KAREN_DOCUMENT_AUTHOR_SOURCE_NAME` | Expected original filename |
| `KAREN_DOCUMENT_AUTHOR_MUTATION_ACCEPTANCE=true` | **Separate explicit permission** to confirm and issue a real receipt from the disposable fixture |

Run `npm run test:e2e:document-author`. Default opt-in performs **read-only** review and proves confirmation is disabled until a deliberate author gesture. The independent mutation gate uses a disposable, author-controlled fixture to exercise human confirmation, live issuance, page reload and receipt recovery. Real HTTP responses and actual credentials are used. There is no request interception, fixture mocking, trace, screenshot, video, JSON report or automatic retry. Authentication is origin locked and uses the existing approved-host login helper.

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

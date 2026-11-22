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

# KCE-FREE-04: Protected File Explorer + Content Intelligence acceptance

## Status and authority

Source integration is merged. No successful live deployment-backed acceptance
is established by source tests or this document. The canonical artifact
repository controls bytes and access; RuntimePolicy, PluginService and
PluginKernel control execution. The File Explorer supplies **references only**.
The only approved release mirror authority is
`scripts/sync_free_plugin_release_mirrors.py` and the release ledger.

## Preconditions (sanitized acceptance environment)

- Use the existing `karen-sanitized-browser-acceptance` GitHub environment and
  approved immutable HTTPS Vercel deployment; source SHA must exactly match the
  current reviewed `main` revision and the deployed code identity.
- Provide the existing protected variables
  `KAREN_FILE_EXPLORER_ACCEPTANCE_URL`,
  `KAREN_CONTENT_INTELLIGENCE_SOURCE_ID`, and Vercel project/org settings.
  Provide `KAREN_UX_EMAIL`, `KAREN_UX_PASSWORD`, Vercel token and automation
  bypass as environment secrets, never a PR description or CLI output.
- The source ID is a genuine owner-owned, undeleted artifact on the first
  owner-inventory page; its canonical PostgreSQL row and Storage bytes must
  correspond, and its SHA-256 revision must match. Use a text/code type
  supported by `read_owner_active_code`, with no private or sensitive content.
- Both `file-explorer` and `content-intelligence` are enabled through the
  governed plugin lifecycle for that actor. The actor has effective
  `data:read` and tenant-scoped RuntimePolicy permission. Do not alter
  production plugin enablement just to make an acceptance test pass.
- The `file-explorer` scenario additionally requires over 100 genuine
  owner-owned artifacts so real cursor paging is exercised. The separate
  `content-intelligence` scenario does not require a second page.

## Existing dispatch, not a parallel runner

Open GitHub Actions > **KAREN Browser Acceptance** > Run workflow, select the
reviewed live `main` branch and enter its exact 40-character SHA in
`target_sha`. Use the existing deployment target selected for the approved
immutable deployment.

Run **file-explorer** first, then **content-intelligence**.

- The workflow checks the requested SHA against the dispatched commit, live
  `main`, independently verified Vercel deployment, and deployed revision.
- The existing Playwright suite signs into Karen with the sanitized account,
  checks real owner inventory, responsive viewports and navigation.
- The `content-intelligence` job sets its acceptance flag and runs only
  `--grep='KCONTENT-LIVE'`. The test requires the seeded source ID, sends the
  real POST to `/api/plugins/content-intelligence/owner-sources`, verifies
  exact source ID and SHA-256 and displays the returned lexical analysis.
- A disabled/missing source, invalid deployment, missing credentials or missing
  source ID is a **failure**, never an approved empty result.
- The workflow runs without browser trace/video/screenshot uploads, and
  reattests deployment and current `main` after the browser proof.

## Additional negative proof before community publication

The happy-path browser case is not a substitute for negative authorization
acceptance. Collect independent **real PostgreSQL/Storage-backed** evidence
that expired/archived/deleted or cross-user/tenant source references are denied,
and that changed revisions cannot be replayed. All tests must be performed
with sanitized fixtures and without dumping bytes, token values or private
filenames into CI logs. Evidence from fake repositories, mocked HTTP routes or
skipped browser tests cannot certify these gates.

## Evidence receipt (fill with real observations only)

Record a completed run's GitHub Actions URL and exact current/deployed SHA in
the release tracking issue. Record successful step names and execution status,
approved fixture type, source owner/tenant segregation result, source revision
and deletion/revocation negative results, and reviewer signoff. Do not paste
credentials, raw document contents, direct Storage URIs or bearer URLs.

If a workflow cannot be dispatched, the deployment is rate-limited, the
required fixture is absent or any gate is missing, record the status as
**blocked/unverified**. Keep File Explorer and Content Intelligence in
`free_plugins/RELEASE_ELIGIBILITY.md` as **Not shipped**. Do not create release
mirror directories until signed-in acceptance and source parity are verified.

## KCE-FREE-05: Read-only two-principal denial acceptance

The protected `content-intelligence-denial` scenario adds a genuine,
read-only browser proof. It requires two **distinct** sanitized authenticated
accounts with working File Explorer and Content Intelligence permissions,
plus distinct real `KAREN_CONTENT_INTELLIGENCE_SOURCE_ID` and
`KAREN_CONTENT_INTELLIGENCE_ISOLATION_SOURCE_ID` artifacts belonging to
respective owners. Store the
second account in GitHub environment secrets `KAREN_UX_ISOLATION_EMAIL`
and `KAREN_UX_ISOLATION_PASSWORD`. No credentials are logged or uploaded.

The test observes both owners' real inventories and SHA-256 evidence and
requires successful Content Intelligence analysis for each owner before testing
denials. Only the exact-host Vercel deployment bypass cookie is copied to the
second isolated browser context, never the first user's application session.
An analysis
request using a forged digest must return HTTP 403. A separate browser context
then signs in as the other account, independently proves that its File Explorer
inventory is accessible, and checks that neither its inventory nor an attempted
analysis can reveal the first owner's artifact. The latter must return HTTP
403. This is **not** a substitute for a verified revoked/deleted source test,
which still requires real PostgreSQL/Storage evidence of revocation.

Run this scenario through the existing protected GitHub Actions workflow on
an approved immutable `main` deployment, with the exact current source SHA.
No route mocks or synthetic credentials qualify. An unavailable acceptance
fixture is an incomplete release gate, not a passing test.

## KCE-FREE-06: Revoked owner artifact, read-only acceptance

The existing protected browser workflow includes the additional
`content-intelligence-revocation` scenario. It uses one sanitized owner
account and two separate artifacts: a valid currently active text source and
an **independently attested** previously active, now deleted/archived source.
The test first establishes successful Content Intelligence admission and
analysis of the active source, then confirms that the retired source does not
appear on the current owner-inventory page and receives HTTP 403 when its
old revision is submitted. It does not mutate source records or storage.

The approved acceptance environment must provide
`KAREN_CONTENT_INTELLIGENCE_SOURCE_ID`,
`KAREN_CONTENT_INTELLIGENCE_REVOKED_SOURCE_ID` and
`KAREN_CONTENT_INTELLIGENCE_REVOKED_REVISION`. They must refer to distinct
owner-controlled artifacts. Missing configuration fails the scenario.

**Do not interpret 403 alone as proof of actual revocation.** Before a live
run can count toward release approval, an authorized reviewer must use
**real PostgreSQL/Storage** evidence to independently establish that the
retired artifact belonged to the same user/tenant, was formerly eligible,
and is now revoked/deleted or archived. Record a sanitized state transition
receipt and actual workflow run URL, excluding raw file contents, credentials
and private storage keys. An unknown source identifier can also yield 403,
so an unverified fixture does not satisfy this gate.

The source implementation and protected scenario may be merged without
declaring consumer acceptance passed. File Explorer and Content Intelligence
remain **Not shipped** until real results, independent revocation proof and
release-mirror parity are all recorded and approved.


## KPLUG-09: Real Storage range proof and browser refresh continuity

**Status: implementation ready for observation, not consumer-certified.**
KPLUG-08 proved source-revision and owner races against real disposable
PostgreSQL and a controlled in-process Storage fixture. KPLUG-09 adds a
distinct opt-in, **real Supabase Storage signed-range** read to the existing
`tests/integration/test_live_code_artifact_revocation_postgres.py`.
The test invokes `SupabasePlatformClient` and the unchanged canonical
`SupabaseArtifactStore.read_owner_active_text_bounded`, without mocked HTTP,
synthetic signed URLs, uploads, ACL changes, or metadata mutation. The
repository must receive an exact 206 Partial Content range, compare the
actual bytes with the migrated disposable PostgreSQL metadata SHA-256, and
deny wrong-owner, wrong-tenant, and undersized transfer-budget requests.

Preconditions, in addition to the existing disposable PostgreSQL proof:
an explicitly disposable Supabase project with a real private
`artifacts` bucket, a preseeded nonsensitive `.txt` or `.md` object,
and an exact matching active, owner-owned `files` row in the local
`karen_code_artifact_test` database. Use exactly the same tested owner
and tenant IDs as the current CK-GEN PostgreSQL fixture. The existing
private acceptance configuration supplies:

- `KAREN_TEST_DISPOSABLE_DATABASE=1` and
  `KAREN_TEST_CODE_ARTIFACT_LIVE_RANGE=1`
- `KAREN_TEST_SUPABASE_DISPOSABLE=1`,
  `KAREN_TEST_SUPABASE_PROJECT_REF` and exact
  `SUPABASE_PROJECT_URL=https://<project_ref>.supabase.co`
- `KAREN_TEST_CODE_ARTIFACT_DATABASE_URL` pointing only to local
  `127.0.0.1:5432/karen_code_artifact_test`
- `KAREN_TEST_ARTIFACT_TENANT_ID`,
  `KAREN_TEST_ARTIFACT_OWNER_ID`,
  `KAREN_TEST_ARTIFACT_OTHER_USER_ID`,
  `KAREN_TEST_LIVE_RANGE_ARTIFACT_ID` and
  `KAREN_TEST_LIVE_RANGE_ARTIFACT_SHA256`
- The canonical platform's configured Supabase project credential,
  held only in the protected acceptance environment, never in GitHub
  source, PR descriptions, or browser variables

On the approved disposable test host, run the existing test file with
`pytest tests/integration/test_live_code_artifact_revocation_postgres.py -q -rs`
and explicitly confirm the live signed-range test **executed and passed**.
A skipped test, a missing preseeded row or a Storage 200 response that
ignored `Range` **does not** satisfy this gate. Existing automatic CK-GEN
CI continues to test PostgreSQL without live Supabase credentials and
must not be described as a successful live Storage run.

For the authenticated consumer proof, reuse the protected existing
`content-intelligence` browser dispatch in
`.github/workflows/karen-history-browser-acceptance.yml`, only on an
immutable exact-`main` approved deployment with sanitized credentials.
Its `KCONTENT-LIVE` test now checks that after successful real analysis,
a real owner-inventory refresh clears the prior selection and displayed
analysis **without automatically replaying a POST**. The user must
explicitly reselect the fresh source reference and click Analyze for
a second backend-verified result. Existing `content-intelligence-denial`
and `content-intelligence-revocation` are still required independent
negative browser scenarios. The refresh-only proof is **not** a substitute
for a controlled live byte-revision change between selection and execution;
the real PostgreSQL concurrency test remains that separate authority.

A successful browser or Storage run requires the actual run URL,
reviewed/deployed SHA, source metadata provenance and sanitized
pass/fail receipt before the release ledger changes. An unconfigured
protected environment, unavailable live Storage fixture, or blocked
Vercel deployment stays **unverified**, not silently passed.


## KPLUG-10: Prove the real Storage handoff to Content Intelligence

**Status: source contract, not an observed live-service pass.** The existing
opt-in `test_live_supabase_object_read_with_disposable_postgres_owner_scope`
now goes beyond downloading the selected object from real Storage. It uses
the same canonical `SupabaseArtifactStore` as the owner-scoped File Explorer
adapter and both runtime hosts. An artifact must appear on the first real
owner inventory page, pass independent source/revision revalidation, and
produce an exact source-ID/SHA-256 lexical analysis after its bytes have
been reread and checked from real Storage. A forged revision must deny
without publishing an additional analysis result.

The test reuses `KAREN_TEST_CODE_ARTIFACT_LIVE_STORAGE=1` and the
`KAREN_TEST_LIVE_ARTIFACT_ID` / `KAREN_TEST_LIVE_ARTIFACT_SHA256`
fixture from the original live object-read proof. No third live-storage
test flag or workflow is introduced. The named Storage bucket must be
independently attested as private and the PostgreSQL target must be local
`karen_code_artifact_test` on port 5432, with an exact disposable
Supabase project URL and credentials. All of these prerequisites must
fail closed if missing; the fixture must be the same active,
nonsensitive artifact selected by the protected browser scenario.

The test-only kernel admission fixture checks the hosts' request contracts
and executes the canonical Content Intelligence lexical engine. **It is not
a production PluginKernel or an authenticated HTTP request**, so it
cannot certify effective RuntimePolicy, RBAC, browser authentication or
deployment wiring. Preserve those independent proof paths through the
existing protected browser workflow and API contract suites.

A normal CK-GEN run keeps both live Storage proofs skipped. Only a
successful explicitly opted-in run with a real object read, validated
source receipt, and sanitized evidence counts toward live Storage
acceptance. Record the exact run URL, source commit and deployment SHA,
approved tenant/owner segregation results, Storage private-bucket
attestation, protected browser scenario results, and reviewer approval.
Never log content bytes, filenames, signing tokens, authentication headers,
or private Storage URLs. File Explorer and Content Intelligence remain
**Not shipped** until those separate proofs have actually passed.

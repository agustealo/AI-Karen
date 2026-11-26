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


## KEXP-024: Independent local Content Intelligence acceptance

The three existing Content Intelligence browser scenarios can be executed on the
same exact-SHA disposable local stack as Explorer, without Vercel or a hosted
provider. This is a distinct read-only invocation of the existing KUI runner,
not a new workflow or a substitute for any hosted deployment attestation.

Before provisioning, explicitly configure the local project's private
`KCARD_LOCAL_STORAGE_URL=http://host.docker.internal:<local-api-port>` and
`KCARD_LOCAL_STORAGE_SECRET_KEY` in the existing private local `.env`. Use only
an independently approved local Supabase project credential (local service-role
or secret key), never a cloud credential. The existing provisioner validates the
configured gateway against the running local database project's Kong container
and copies only this opt-in pair into the private generated acceptance env.
No bucket or artifact is created by the runner. Confirm the local project and
private artifacts bucket are dedicated to this trial; seed real matching
metadata and Storage objects using the existing governed artifact owner. Confirm
and record the retired fixture's former eligible state and subsequent revocation.

Use the existing disposable stack and private env path, the exact reviewed SHA,
loopback `http://127.0.0.1:8010`, two distinct sanitized accounts, and three distinct
canonical fixture UUIDs. Set `KAREN_LOCAL_CHAT_ACCEPTANCE=1`,
`KAREN_SANITIZED_ACCOUNT=true`, `KAREN_FILE_EXPLORER_ACCEPTANCE=true`,
`KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED=true`, and the three existing
Content Intelligence acceptance flags. Set
`KAREN_CONTENT_INTELLIGENCE_LOCAL_STORAGE_CONFIRMED=true` and
`KAREN_CONTENT_INTELLIGENCE_REVOKED_FIXTURE_ATTESTED=true` only after the
independent fixture checks. Supply the active, isolation and retired source IDs
and retired SHA-256 described above; keep credentials in the private shell.
Unset hosted verification flags, Vercel bypass credentials and Explorer mutation
flags. Run separately from Explorer and Card Studio:

```bash
RUN_CONTENT_INTELLIGENCE_LOCAL=1 bash scripts/ci/kui-local-acceptance.sh "$EXPECTED_SHA"
```

The runner verifies exact clean source, loopback web ingress, API database
identity, running local Storage gateway and image/container/database continuity
before and after the three scenarios. Discovery must identify exactly three
Chromium tests; execution must pass each once without retries/skips/failures.
Reports are private and outside the checkout. The explicit retired-fixture
attestation remains required; a 403 alone is not a revocation proof. The two
standalone Storage integration tests still require their separate approved real
Storage fixtures. No consumer acceptance result is claimed by this source change.


## KEXP-025: Standalone real Storage proofs without a hosted project

The existing CK-GEN opt-in object-read and signed-range tests also accept a
private disposable **local** Supabase project. The runtime repository's
HTTPS/loopback origin, signed path, range, digest, budget and owner checks are
unchanged. Both tests now accept the canonical immutable `/content` object
key produced by the governed upload path, as well as the repository's
explicitly supported historical filename key. They never guess an object key.

Use a local Docker daemon and an explicitly disposable Supabase CLI project
with its API gateway published **only** on `127.0.0.1`. Start it with an
approved isolated network and verify the actual port/container names before
setting the configuration. Do not link, reset or contact a hosted project.
The local CLI version and stack configuration determine the port; do not
assume the default. Keep the server credential private and unset proxy
variables for this dedicated test invocation. No cloud project reference
may be inherited. The standalone test process runs on the host, not inside
the API container; its origin is loopback, not `host.docker.internal`.

Retain the existing separately disposable, migrated PostgreSQL
`karen_code_artifact_test` database on loopback port 5432. Use the canonical
CK-GEN workflow's schema provisioning and seeded principals; do not reuse or
modify the personal database. Seed independently approved nonsensitive
object bytes and matching metadata for the existing live-object and range
fixture IDs/digests. Verify the bucket is private. These tests are read-only
and will not create fixtures. Provide all existing tenant/owner/other-owner,
artifact and SHA-256 variables, with the additional local-only configuration:

- `KAREN_TEST_DISPOSABLE_DATABASE=1` and `KAREN_TEST_SUPABASE_DISPOSABLE=1`
- `KAREN_TEST_SUPABASE_LOCAL=1`
- `KAREN_TEST_SUPABASE_LOCAL_PROJECT_ID` matching the running local project's
  `supabase_db_<project-id>` and `supabase_kong_<project-id>` container names
- `SUPABASE_PROJECT_URL=http://127.0.0.1:<verified-api-port>`
- A private local `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`
- Unset `KAREN_TEST_SUPABASE_PROJECT_REF`, remote Docker overrides and proxies.

Then execute both existing trials, separately from hosted/browser acceptance:

```bash
KAREN_TEST_CODE_ARTIFACT_LIVE_STORAGE=1 KAREN_TEST_CODE_ARTIFACT_LIVE_RANGE=1 \\
  PYTHONPATH=src python -m pytest -q -rs \\
  tests/integration/test_live_code_artifact_revocation_postgres.py \\
  -k 'live_supabase_object_read or live_signed_range_read_uses_real_storage'
```

Require exactly two executed successful trials with no skips. Local Storage
must actually return HTTP 206 for the signed-range test; a 200 response is
not sufficient. Record exact source SHA, sanitized pass/fail output and
local gateway/private-bucket/fixture provenance. Local success is not a
hosted deployment receipt or an automatic release authorization.

### Local provisioning configuration convergence

The shared local acceptance provisioner and provenance verifier now derive
the database project's name and host port from the repository's existing
`supabase/config.toml`. The generated private env exports `KCARD_DB_PORT`
for Compose; API connection URLs and the effective container must match
that exact configured port. Do not substitute the Supabase CLI default
port or point the acceptance database at a different project. This repository's
current checked-in database port is 54342. The standalone CK-GEN disposable
PostgreSQL proof remains independently constrained to port 5432.

### Local provisioning preflight

The deployment provisioner requires a fresh private acceptance state directory
outside the checkout. The default exact-SHA directory is suitable on the first
run; use an explicitly fresh `KAREN_KCARD_STATE_DIR` for another attempt only
after separately verifying the disposable database and Compose project are safe
to reuse or remove. Existing state and databases are never overwritten or reset.
Before creating a database, the provisioner validates the generated dotenv
configuration and reads the complete canonical migration inventory. Missing or
unreadable migrations and invalid configuration stop before database creation.
The reserved state directory is mode 0700; credentials remain mode 0600.
A failed migration or build may leave disposable state for diagnosis. Do not
interpret it as deployment readiness or automatically delete it.

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

# KAREN Browser Contracts

This directory contains Playwright browser-level contracts for the KAREN web UI. It does **not** own provider selection, provider availability, production authentication, or real-runtime readiness.

## Authority boundaries

- `test_first_run_setup.spec.ts` verifies first-run UI behavior. It uses Playwright route stubs deliberately, so it is a browser contract rather than production-runtime proof.
- `scripts/ci/production-first-boot-smoke.sh` is the canonical fresh-install production boot proof. It creates a real database, Redis service, tenant and installation owner against the production API image.
- `e2e/playwright.showcase.config.ts` plus `e2e/showcase/capture-product.showcase.ts` own trusted real-product presentation capture against an approved sanitized running installation.
- Provider and model availability come from the backend provider registry and runtime control plane. Browser tests must not assume Gemini, another cloud provider, or a retired built-in runtime is enabled.

## Local browser-contract setup

From `src/ui_launchers/Karen-AI-Theme/e2e`:

```bash
npm ci
npm run install
```

Run the KAREN frontend separately, then execute:

```bash
KAREN_BASE_URL=http://localhost:8010 npm test
```

Useful commands:

```bash
npm run test:headed
npm run test:ui
npm run test:debug
npm run report
```

`KAREN_BASE_URL` defaults to `http://localhost:8010` when omitted.

## Real local CopilotKit first-turn and replay acceptance

The existing `copilotkit-consumer-boot.spec.ts` now supports a **local-only**
opt-in using the same authenticated, no-mock assertions as the release suite.
This is a real running-stack proof, not the stubbed first-run UI contract.

Start local Supabase and apply canonical migrations using the repository's
supported Supabase workflow, then start the existing local Compose services
with `bash scripts/dev/start_docker_services.sh`. Finish the actual first-run
owner setup, configure a healthy model in Karen's canonical provider registry,
and use a dedicated authorized local test account. Do not add fixture secrets
or login bypasses to source control.

From `src/ui_launchers/Karen-AI-Theme/e2e`:

```bash
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
npx playwright test copilotkit-consumer-boot.spec.ts --project=chromium
```

Set `KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` as local shell environment
variables before running. An authorized `KAREN_E2E_AUTH_STATE` may be used
instead; keep any storage-state file private and outside version control.
Local mode refuses non-loopback hosts, non-HTTP origins, URL credentials,
paths, query strings and mixed release/local mode. Its backend check must
return `backend_ready: true` from the real same-origin API before it signs in.
It tests one genuine first prompt, backend model execution provenance,
time/weather/search/movie presentation on first send, persisted history and
reload/replay. External data and actual provider availability can cause real
failures; the suite must not replace them with scripted output.

The **release** invocation remains separate:
`KAREN_CHAT_BOOT_ACCEPTANCE=1` with a reviewed HTTPS deployment,
`KAREN_CHAT_BOOT_REVISION` equal to the exact 40-character commit, and
approved credentials. Local mode skips only the deployment-SHA assertion
because a development server may not expose a deployed revision. It does not
skip API readiness, identity, real model execution, saved receipts or replay.
Both modes disable traces, screenshots and videos to avoid credential and
conversation capture. A green source gate is never substituted for a real
local browser run.

## Authentication rules

Do not add repository-wide default usernames or passwords to browser tests. A fresh KAREN installation creates its owner through the canonical first-run flow. Tests that need a real authenticated installation must receive credentials through the specific trusted harness that owns that environment.

The presentation harness is intentionally stricter: it requires a sanitized demo account and refuses fixture-generated or mocked product evidence.

## Provider/runtime rules

Provider-specific browser tests must be explicit opt-in tests bound to a known configured environment. They must not be part of the generic browser suite merely because a provider existed historically.

The retired Gemini-era specs were removed because they simultaneously assumed:

- a fixed legacy admin credential;
- Gemini was always configured and enabled;
- an old provider-settings UI contract;
- legacy built-in runtime availability.

Those assumptions are no longer valid sources of truth. Provider routing and fallback behavior are proven by the dedicated backend/runtime gates.

## Real production proof

For fresh-install behavior, use the repository-owned production smoke path rather than expanding browser mocks:

```bash
bash scripts/ci/production-first-boot-smoke.sh
```

The corresponding GitHub Actions workflow builds the production API and web images before executing that smoke contract.

## Real presentation proof

The showcase suite is separate from the generic browser contracts because it captures repository-promotable evidence. It requires:

- a trusted default-branch harness;
- a sanitized real installation;
- exact target revision provenance;
- no mocked responses or generated UI;
- canonical gallery verification before repository write.

Do not weaken that boundary to make screenshots easier to produce.

## Governed authenticated identity replay

The canonical `Beta Live Model Smoke` workflow has an opt-in
`run_authenticated_browser_replay` dispatch input. It reuses
`e2e/ux-personal-memory-replay.spec.ts`; no separate CI pipeline,
browser harness, synthetic model response, or packaging job is needed.

Only dispatch the workflow **from `main`** after deploying that exact commit to
an approved HTTPS beta installation with a healthy real model. Set these values
on the protected `beta-release` GitHub environment:

- Variable `KAREN_UX_BASE_URL`: approved HTTPS origin (no path).
- Variable `KAREN_UX_DEPLOYMENT_REVISION`: the exact deployed 40-character
  commit SHA; it must equal the dispatch workflow's checkout SHA. This is an
  **operator attestation**, not independent binary-deployment verification.
- Secrets `KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD`: dedicated sanitized
  account that is allowed to log in and use chat.

From GitHub Actions, choose **Beta Live Model Smoke**, select **Run workflow**
on `main`, and turn on **Run real, authenticated personal-memory browser
acceptance**. The additional Ubuntu job validates prerequisites, installs the
existing frontend's locked dependencies and Chromium, then runs the identity
replay with full-session video enabled. It fails closed if the environment or
credentials are missing, the URL is not HTTPS, or the attested revision differs.

The existing self-hosted Windows live-model job is not replaced. Its queue
state is independent of the opt-in browser job. Inspect both job conclusions
instead of reporting an overall green result from just one.

The GitHub artifact is retained for seven days and may contain chat
text, screenshots and browser recordings. Credential-bearing Playwright traces
are disabled for this opt-in suite and ZIP traces are excluded from upload.
Old report directories are cleared before execution; rerun artifacts use their
unique run attempt. GitHub artifacts remain accessible to repository readers,
so do not treat them as secret storage. Authorized reviewers must
inspect and sanitize it before any public publication. The Playwright assertion
receipt explicitly does not prove NeuroVault long-term memory projection.
Do not mark release acceptance complete merely because the workflow dispatch
was accepted, skipped, or queued.


## KARI OS Automations authenticated five-viewport acceptance

The opt-in `automation-visual-acceptance.spec.ts` is the source-owned live
browser contract for Tasks, Jobs and Cron. It reuses
`fixtures/approved-karen-login.ts`, navigates the actual Dashboard controls,
and requires a real authenticated HTTP 200 JSON list from each of
`/api/tasks/`, `/api/automation/jobs/`, and `/api/automation/cron`.
No route interception or synthetic list fixtures are allowed.

Use a dedicated sanitized account with access to the three endpoints, a persisted
**System** display-theme preference, and an approved, healthy deployment.
The suite asserts the resolved document theme after changing browser color
scheme. It fails closed when an explicit Dark/Light account setting overrides
the browser preference; it never silently reports both themes as tested. Example local invocation:

```bash
cd src/ui_launchers/Karen-AI-Theme/e2e
KAREN_AUTOMATION_VISUAL_ACCEPTANCE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
npx playwright test automation-visual-acceptance.spec.ts --project=chromium --retries=0
```

For an approved HTTPS target, omit `KAREN_LOCAL_CHAT_ACCEPTANCE`. The
existing login fixture rejects credential-bearing URL components and
unapproved origins. Configure credentials in your trusted local environment,
never in source control.

Five viewport widths (390, 768, 1024, 1440 and 1920px) are checked in
dark and light browser color schemes, including viewport/document geometry,
visible panels, and actual keyboard focus. The test observes real backend
list responses and allows a verified empty list only after HTTP 200. It does
not mutate scheduled work, create tasks, or certify backend execution.

Traces, videos and automatic screenshots are disabled because the browser
enters credentials. Optional screenshots require
`KAREN_AUTOMATION_SANITIZED_CAPTURE=true` **and** an independently approved
sanitized identity. Inspect every artifact before distribution. CI source
checks and a skipped opt-in suite are **not** evidence of a completed real
browser run. This contract does not yet prove principal-switch stale response
fencing, backend-disconnect fault injection, visual pixel parity, or
production deployment revision identity. Those remain separate acceptance
gates and must be recorded independently.


## Two-account Automation isolation acceptance

`automation-two-account-acceptance.spec.ts` is a separate **opt-in, real
backend** A-to-B session acceptance gate. It does not create/delete tasks,
execute jobs, replay fabricated API responses, or intercept network traffic.
It reuses the existing approved-origin authentication fixture and the same
Dashboard navigation helper as the visual acceptance spec.

Before running, provision **two distinct, authorized, sanitized accounts**
with their own existing, uniquely named task, job and Cron resources.
Markers must exactly match each resource's backend `name`, or Cron
`taskName` when present. Each account must be able to read its own three
workspaces, but **not** the other account's marker-bearing resources. These
data prerequisites are intentionally fail-closed, not synthesized by a test.

```bash
cd src/ui_launchers/Karen-AI-Theme/e2e
KAREN_AUTOMATION_TWO_ACCOUNT_ACCEPTANCE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
KAREN_UX_ACCOUNT_B_EMAIL="$KAREN_UX_ACCOUNT_B_EMAIL" \
KAREN_UX_ACCOUNT_B_PASSWORD="$KAREN_UX_ACCOUNT_B_PASSWORD" \
KAREN_UX_ACCOUNT_A_TASK_MARKER="$KAREN_UX_ACCOUNT_A_TASK_MARKER" \
KAREN_UX_ACCOUNT_B_TASK_MARKER="$KAREN_UX_ACCOUNT_B_TASK_MARKER" \
KAREN_UX_ACCOUNT_A_JOB_MARKER="$KAREN_UX_ACCOUNT_A_JOB_MARKER" \
KAREN_UX_ACCOUNT_B_JOB_MARKER="$KAREN_UX_ACCOUNT_B_JOB_MARKER" \
KAREN_UX_ACCOUNT_A_CRON_MARKER="$KAREN_UX_ACCOUNT_A_CRON_MARKER" \
KAREN_UX_ACCOUNT_B_CRON_MARKER="$KAREN_UX_ACCOUNT_B_CRON_MARKER" \
npx playwright test automation-two-account-acceptance.spec.ts \
  --config=playwright.config.ts --project=chromium --retries=0
```

For an approved HTTPS release host, omit `KAREN_LOCAL_CHAT_ACCEPTANCE`.
Provide real credentials and marker names through a trusted local environment
or protected CI environment; never commit them to source or logs. No
screenshots, videos or traces are recorded. The test asserts HTTP 200 JSON
lists for each identity, verifies the appropriate marker and rejects the
other identity's marker, signs out through **My Account**, requires an
unauthenticated API read to return 401 or 403, then signs in as account B
and repeats those assertions.

A green source/CI contract or skipped opt-in test is not evidence of a
completed host execution. This suite validates sequential real-account
switching and logout denial, **not** deliberate in-flight A-response replay
after B login, same-principal reauthentication races, injected network
disconnects, scheduler execution, or actual deployed-SHA provenance. Keep
those gates open until separately observed on an authorized environment.

## KARI OS Application Settings five-viewport acceptance

`settings-visual-acceptance.spec.ts` exercises the **merged canonical
Application Settings shell** as a full dashboard page and a right-side
Settings drawer. It keeps the existing real login fixture, runtime-owned
panel data, and readonly keyboard/category navigation. There are no network
intercepts, fake settings, changed user preferences, or backend writes.

Provision an approved sanitized account with access to the dashboard. Provide
credentials through the operator's trusted shell (do not commit them or enable
shell command echoing). From `src/ui_launchers/Karen-AI-Theme/e2e`:

```bash
KAREN_SETTINGS_VISUAL_ACCEPTANCE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
npx playwright test settings-visual-acceptance.spec.ts \
  --config=playwright.config.ts --project=chromium --retries=0
```

The local example uses explicitly authorized loopback only. For an approved
HTTPS origin, omit `KAREN_LOCAL_CHAT_ACCEPTANCE`. Supply
`KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` securely in the environment.

Both modes check 390, 768, 1024, 1440 and 1920 CSS-pixel viewports, computed
KARI OS graphite tokens, document and panel horizontal overflow, accessible
category/section navigation, and keyboard selection. The sheet must remain
**stacked even at desktop viewport widths**; only the full page gains the
240px left rail.

Traces, video, and automatic screenshots are off. For independently approved
sanitized artifacts only, set `KAREN_SETTINGS_SANITIZED_CAPTURE=true`.
Check the attachments for sensitive content before any distribution. The
test does not prove persisted theme switching, successful settings mutation,
or pixel-fidelity against a design reference. A skipped opt-in test or green
GitHub source check **is not real browser acceptance evidence**.


## Real Automation network-disconnect and same-account re-login acceptance

`automation-transport-recovery.spec.ts` is a separate opt-in, authenticated
browser test. It verifies that an existing sanitized Jobs resource is read
from the real backend, a single deliberately aborted GET produces a visible
**unavailable** notice rather than a false **empty** notice, and a fresh
unmodified backend GET restores the resource. It then signs out through the
real account UI, requires backend denial (401/403), and signs into a fresh
session for the **same** account to verify a new real resource read.

Provision a healthy, authorized, sanitized host and a dedicated account with
a uniquely named, already existing Jobs resource. Provide credentials via
trusted environment variables, never a committed fixture:

```bash
cd src/ui_launchers/Karen-AI-Theme/e2e
KAREN_AUTOMATION_TRANSPORT_ACCEPTANCE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
KAREN_UX_ACCOUNT_A_JOB_MARKER="$KAREN_UX_ACCOUNT_A_JOB_MARKER" \
npx playwright test automation-transport-recovery.spec.ts \
  --config=playwright.config.ts --project=chromium --retries=0
```

For a reviewed HTTPS release origin, omit the local-loopback flag. The
existing approved login helper validates the origin before accepting
credentials. The suite disables traces, screenshots, and videos; do not
upload credential-bearing browser artifacts. The one fault is an intentional
`route.abort("failed")` of a browser GET, with no fabricated HTTP response,
no fake JSON, and no mutating automation call. Every successful recovery is
a real backend response.

This test **does not** establish a real-host pass until explicitly executed
against that host. It also does not prove controlled old-session response
delivery after a new login, cross-tab logout races, or deployment revision
provenance. Those remain separate release acceptance gates.


## Plugins & Tools: authenticated five-viewport acceptance

The opt-in `plugins-visual-acceptance.spec.ts` verifies the **merged** Kari OS
Plugins & Tools overview against the *real* authenticated extension registry.
The browser records `GET /api/extensions/list` during login, validates its
contract and compares displayed registry counts and card totals with that exact
response. It does not infer active execution, fake connection readiness, or
mutate any plugin. Lifecycle mutations require separate authorized acceptance.

From `src/ui_launchers/Karen-AI-Theme/e2e`, with an approved running local
backend/frontend and a dedicated sanitized account:

```bash
KAREN_PLUGINS_VISUAL_ACCEPTANCE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
npx playwright test plugins-visual-acceptance.spec.ts \
  --config=playwright.config.ts --project=chromium --retries=0
```

On an approved HTTPS host, omit the local-acceptance flag.
The sign-in fixture rejects non-loopback HTTP and credential-bearing URLs.
The test checks 390, 768, 1024, 1440 and 1920px geometry, shared Kari OS
tokens, visible plugin counts and keyboard-reachable installation navigation.
It does **not** click plugin lifecycle buttons or claim backend permission
verification from button appearance alone.

Video, traces and automatic screenshots are disabled. Optional evidence
requires `KAREN_PLUGINS_SANITIZED_CAPTURE=true` and a dedicated sanitized
account whose UI contains no personal data or secrets. Review screenshots
manually against the approved design reference. A CI run that skips this
opt-in suite is not browser or release acceptance.


### Protected Settings acceptance on reviewed main

The existing **KAREN Browser Acceptance** GitHub Actions workflow also offers
the operator-triggered `settings` scenario. Dispatch it on `main`, with
`target_sha` set to that same reviewed, current 40-character main commit and
`deployment_target` set to `preview` or `production`. Supply the approved,
**immutable HTTPS Vercel deployment URL** in the protected environment variable
`KAREN_SETTINGS_ACCEPTANCE_URL`. The environment
`karen-sanitized-browser-acceptance` must provide authorized
`KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` secrets and the canonical
Vercel provenance credentials/IDs used by other protected acceptance jobs.

The job fails closed before browser setup if the Git ref, checked-out SHA,
independent Vercel Git provenance, live deployment revision, or environment
configuration does not match. It attests both platform and live deployment
identity again after the browser run. The acceptance suite is opted in only
for that job; no screenshots, traces, video, report uploads, fake backend
data, or browser test retries are permitted. An absent deployment, unconfigured
secret, Vercel quota block or stale main SHA **fails or blocks acceptance**;
it never counts as a browser pass. Protect environment approvals and never
copy real account values into workflow inputs or logs.

## Exact-head local UI acceptance runner

The repository-owned `scripts/ci/kui-local-acceptance.sh` consolidates the
existing backend, frontend and Plugins & Tools browser contracts. Unlike a
passing GitHub source workflow, it can run the **real** authenticated plugin
catalog test on the approved KAREN host. It does not deploy services, install
plugins, change RBAC permissions, or synthesize plugin state.

From a **clean checkout of the intended 40-character commit** at repository
root, with KAREN running and a dedicated sanitized account already provisioned:

```bash
RUN_BROWSER=1 \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
bash scripts/ci/kui-local-acceptance.sh "$(git rev-parse HEAD)"
```

Omit `RUN_BROWSER=1` for source-only checks. That mode explicitly records
`NOT_RUN plugins_live_browser`, never a real-browser pass. Authenticated
Playwright results require one **non-skipped passing** Plugins & Tools test;
other outcomes fail closed.

The runner writes owner-private logs and Playwright JSON outside the checkout
under `${XDG_STATE_HOME:-$HOME/.local/state}/ai-karen/kui-acceptance/<sha>/`,
or the explicit `KAREN_KUI_ACCEPTANCE_OUTPUT_DIR`. Treat reports as
sensitive because they may contain sanitized account metadata. Screenshot
attachments remain opt-in via `KAREN_PLUGINS_SANITIZED_CAPTURE=true` and
`KAREN_SANITIZED_ACCOUNT=true` on an independently approved sanitized host.
Never publish local Playwright artifacts without privacy review.

A runner pass verifies backend/frontend source checks and live plugin layout
contracts at five viewports. It does **not** prove screenshot pixel parity,
real plugin enable/disable operations, production deployment revision, or a
consumer-ready release. Those require their own witnessed evidence.

## Shared File Explorer live owner-inventory browser acceptance

The opt-in `file-explorer-real-acceptance.spec.ts` is a **no-mock** consumer
acceptance contract for the canonical dashboard File Explorer after the
authenticated API and dynamic `PluginHost` integration. It uses
`fixtures/approved-karen-login.ts`, the existing Playwright runner,
`/api/extensions/list` as the canonical plugin catalog and the real
`GET /api/plugins/file-explorer/inventory` request through the frontend
`apiClient`. It never manufactures entries, changes plugin lifecycle,
uploads artifacts, or treats display references as permission to read bytes.

Prerequisites: a real healthy KAREN API and web frontend backed by migrated
PostgreSQL; File Explorer installed and **enabled** for the dedicated sanitized
account; authentic tenant/user identity with `data:read` permission;
at least one owned, non-deleted ArtifactStore file; and a browser-accessible
approved origin. To prove server keyset pagination, first create more than
100 **genuinely owned** artifacts in that test account and set
`KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE=true`. No static fixtures or
route stubs substitute for this evidence.

Run the existing Chromium harness:

```bash
cd src/ui_launchers/Karen-AI-Theme/e2e
KAREN_FILE_EXPLORER_ACCEPTANCE=true \
KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
KAREN_UX_EMAIL="$KAREN_UX_EMAIL" \
KAREN_UX_PASSWORD="$KAREN_UX_PASSWORD" \
npx playwright test file-explorer-real-acceptance.spec.ts \
  --config=playwright.config.ts --project=chromium --retries=0
```

For an approved HTTPS release origin, omit
`KAREN_LOCAL_CHAT_ACCEPTANCE`; the login fixture rejects
credential-bearing URLs and unapproved origins. Opt-in disabled means
**skipped, not passed**. The suite requires a real authenticated HTTP 200,
verifies the source-envelope and exact displayed file count, validates real
cursor progression when a page is available, verifies refresh, keyboard focus,
and checks layout at 390, 768, 1024 and 1440px. Any failed authorization,
missing enabled plugin, unavailable backend, fabricated empty result, or
responsive overflow is a failure. It does not silently downgrade to a
mock-based UI contract.

The observed browser run also checks a genuine file checkbox selection at all
four widths, verifies that the host retains the same selected file during
responsive transitions, ensures **Next page** clears the prior-page selection,
requires the exact backend-issued keyset cursor in the next HTTP request, and
proves **Refresh** drops both stale selection and cursor. These are browser
presentation assertions against real server inventory, not file-byte grants.

This credential-bearing run disables traces, videos and automatic screenshots;
avoid uploading raw browser profiles or account inventory to CI artifacts.
Keep exact deployed revision and operator authorization evidence separately.
Passing this suite proves the observed read-only display path on the tested
installation. It does **not** prove owner-reference TOCTOU resistance for
future download consumers, session switching between two real accounts,
artifact deletion concurrency, arbitrary folder hierarchies, or performance
under load; those remain separate acceptance requirements.

### Protected live acceptance dispatch

The existing `KAREN Browser Acceptance` GitHub Actions workflow now exposes
`scenario=file-explorer`. It reuses the single protected
`karen-sanitized-browser-acceptance` environment, source revision,
Vercel deployment attestation, credential injection, and post-run provenance
verification used by the existing Settings and Navigation scenarios.

Before dispatch, prepare the **same immutable reviewed `main` revision**
on an approved HTTPS Vercel target that has a healthy PostgreSQL-backed
ArtifactStore, an enabled File Explorer extension and an authorized sanitized
account owning **more than 100** active files. Configure protected environment
variable `KAREN_FILE_EXPLORER_ACCEPTANCE_URL` to that target origin, and
existing `KAREN_UX_EMAIL` / `KAREN_UX_PASSWORD` secrets to the account.
The existing Vercel project/organization and verification secrets must be
configured for that deployment. Never write credentials, artifact data or
storage state into repository source.

From **Actions → KAREN Browser Acceptance → Run workflow**, choose `main`,
set scenario to `file-explorer`, provide the exact reviewed 40-character
`target_sha`, and select the correct `deployment_target`. The job will
reject stale source/deployment revisions and will fail if credentials, the
plugin, real owner files or a second page are missing. It executes
`file-explorer-real-acceptance.spec.ts` using the existing Chromium runner,
no retries, with trace/video/screenshot capture and report artifact output
disabled. No new broad test permissions are granted.

A dispatched or skipped workflow is **not** a passed browser observation.
Read the scenario job's actual conclusion before calling File Explorer
consumer-ready. This read-only proof still does not establish safe download,
two-account concurrency, concurrent deletion or throughput under load.


## KGUI-CARD-STUDIO-01E: genuine Card Studio layout browser acceptance

`card-studio-live-acceptance.spec.ts` is the **existing protected
Playwright/Chromium harness** extended for Card Studio, not another UI
renderer or synthetic test account. The test reuses
`fixtures/approved-karen-login.ts`, verifies authenticated HTTP 200 JSON
for the real backend host catalog and owned templates, and exercises the
actual Dashboard Advanced Tools → Card Studio navigation.

**Read-only browser proof:** Exact viewports of 390×844, 768×1024, 1024×768
and 1440×900 CSS pixels, viewport overflow/geometry, unbound preview,
real keyboard Tab traversal, and slot movement. A missing/disabled backend
is **failure**, not an empty fake catalog or a mock fallback.

**Disposable mutation proof:** Only on a deliberately approved **preview**
deployment or an explicitly approved local disposable installation:
real create receipt, reload/readback, two-tab revision competition (a real
HTTP 409), manual reload of the current server revision, archive, and
a transport-disconnect trial. The disconnect calls Playwright `route.fetch()`
against the **real** server and waits for its successful committed response,
then intentionally drops *only* the browser response; the next user-triggered
retry must reuse the identical idempotency key and request body and return
the same template ID/revision. **No JSON or model response is mocked.**
Each successful disposable template is archived. If a trial fails mid-flow,
inspect the specially named `card-e2e-*` or `retry-e2e-*` records on the
approved disposable account before rerun.

**Protected GitHub invocation:** Use the existing **KAREN Browser Acceptance**
workflow on current `main`, scenario **card-studio**, deployment target
**preview**, and `target_sha` exactly equal to the approved deployed main
commit. The protected `karen-sanitized-browser-acceptance` environment
must supply the existing `KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD`
secrets, the new approved `KAREN_CARD_STUDIO_ACCEPTANCE_URL` variable,
and **`KAREN_CARD_STUDIO_MUTATION_APPROVED=true`**. The deployment must be
independently Vercel-attested and have the operator-enabled
`KARI_ENABLE_CARD_STUDIO_CRUD=true` backend setting, with **disposable
resources only**. The repository default remains `false`. No workflow
writes that feature setting for the operator.

The acceptance job runs the existing source/revision/approved-identity
checks before Playwright, repeats Vercel deployment/revision and live
main-commit checks afterward, and uploads **no private trace, screenshot,
recording, login state or JSON report**. It has zero retries.

For an **authorized local disposable environment**, start the normal KAREN
stack with the feature explicitly enabled for that instance, provision a
dedicated real account, then run from
`src/ui_launchers/Karen-AI-Theme`:

```bash
KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE=true \
KAREN_CARD_STUDIO_MUTATION_APPROVED=true \
KAREN_SANITIZED_ACCOUNT=true \
KAREN_LOCAL_CHAT_ACCEPTANCE=1 \
KAREN_BASE_URL=http://127.0.0.1:8010 \
npx playwright test e2e/card-studio-live-acceptance.spec.ts \
  --config=e2e/playwright.config.ts --project=chromium --reporter=list --retries=0
```

Supply the existing `KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD` as
secure local shell variables, never embedded in commands, committed test
fixtures or screenshots. If the account and environment are independently
approved **sanitized**, an operator may opt into local
`KAREN_CARD_STUDIO_SANITIZED_CAPTURE=true` to attach inspected viewport
screenshots. These are never automatically uploaded by the protected
workflow. A green code/CI gate **does not** mean an authenticated real-host
browser trial has been executed. Observe the dispatched job and its receipt
before claiming consumer-browser certification.


### KGUI-CARD-STUDIO-01G: protected Vercel browser session

Card Studio MUST import Playwright `test` and `expect` from the existing
`e2e/fixtures/verified-search-deployment.ts` rather than directly from
`@playwright/test`. The protected workflow already sets
`KAREN_SETTINGS_VERIFIED_DEPLOYMENT=true` for this scenario, and the
shared fixture uses that flag to establish a first-party `_vercel_jwt`
cookie before typing the sanctioned sanitized login credentials.

The bypass secret is sent **once** via the existing `context.request`
to the independently verified immutable Vercel origin with redirect
checks. It is not added to page headers, external requests, recordings
or saved state. The fixture rejects a missing or improperly scoped cookie.
Locally approved disposable loopback runs omit that protected Vercel step.

This fixes a false-negative release-gate path: a valid preview could
previously show Vercel deployment protection instead of Karen's login
page. It does NOT authorize preview deployment, feature activation or
database mutation and does NOT itself certify real-host browser acceptance.


### KGUI-CARD-STUDIO-01H: independently authenticated owner isolation

The approved `card-studio` protected workflow now **requires two distinct
sanitized accounts**: existing `KAREN_UX_EMAIL` /
`KAREN_UX_PASSWORD` and existing
`KAREN_UX_ISOLATION_EMAIL` /
`KAREN_UX_ISOLATION_PASSWORD` protected environment secrets.
Both must be authorized to use Card Studio on the approved disposable
preview; do not use normal user accounts. Local disposable execution likewise
requires both credential pairs via secure environment variables.

A new `KCARD-LIVE-ISOLATION` Chromium trial signs in as the first owner
and creates a genuine PostgreSQL-backed template. It launches a fresh
BrowserContext with **no shared Karen cookies or browser storage**, copying
only the already-verified, exact-origin `_vercel_jwt` deployment-protection
cookie when needed. A genuinely signed-in second user must have a **different verified
login user ID**, must create their own disposable template and obtain an
actual committed HTTP 200 receipt, and must receive HTTP 200
for their own Card Studio inventory. They must not see the first owner's template
in the GUI or the owner inventory, and must receive **403/404** for attempts
to read its current revision, revision list, historical revision, revise it
or archive it. HTTP 401 or an unavailable second-user catalog cannot count
as an isolation success.

The foreign account's own fixture must also be archived via a verified
server receipt even when a denial assertion fails. The test then
independently reads the original owner's authoritative record
and verifies its template ID, title, template key, revision 1 and draft
lifecycle are unchanged. It attempts to archive the disposable owner record
even on a failing trial, reporting cleanup failures rather than concealing
or guessing their outcome. On interruption, inspect `isolation-e2e-*`
records in the approved disposable backend before rerunning.

This strengthens release evidence; the already existing backend RuntimePolicy,
RBAC, PostgreSQL RLS, API transport and default-disabled production feature
remain the sole authorities. Source and CI passes are not evidence that the
two-account live scenario actually ran on an approved host.


### KGUI-CARD-STUDIO-01I: reject green-but-skipped release trials

The dedicated Card Studio Playwright spec is opt-in for ordinary development,
where skipped cases must not require production credentials. The **protected**
GitHub browser job is different: it sets the existing
`KAREN_SETTINGS_VERIFIED_DEPLOYMENT=true` admission marker. When that marker
is present, the spec now fails immediately unless all three release
preconditions are satisfied: `KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE=true`,
`KAREN_CARD_STUDIO_MUTATION_APPROVED=true`, and both sanctioned sanitized
credential pairs are supplied.

This is a release-evidence guard, **not** permission to turn on Card Studio
or execute mutations against arbitrary installations. The environment,
deployed revision, Vercel provenance, real RBAC, PostgreSQL identity scope,
and actual browser tests still have to pass. Ordinary non-protected
Playwright discovery keeps the suite disabled by default. A command that
reports only skipped tests must never be described as real-browser proof.
The existing architecture-source contract guards the marker, prerequisite
identity checks, three live trial names, and absence of a workflow grep
that could select only one of the three cases.


### KGUI-CARD-STUDIO-01J: principal-scoped idempotency receipt proof

The live two-account Chromium scenario now challenges the canonical mutation
receipt boundary with **the same idempotency UUID** from two genuinely
authenticated, write-authorized users. User B submits an independently valid
draft using A's committed request key. The server must return HTTP 200 with
B's own template and receipt, never A's immutable snapshot; an identical retry
by B must return precisely B's prior committed result. User B can read the new
record, while user A must not be able to read B's record. All additional
disposable records are archived with verified server acknowledgments, and
cleanup failures fail the trial rather than being silently ignored.

The existing real-PostgreSQL integration trial additionally proves this
behavior for two users in one tenant and a third user in a different tenant,
using the exact same idempotency UUID, with owner RLS still denying foreign
reads. The runtime, repository, API route, migrations, and production feature
default are unchanged. The real browser proof still requires the approved,
sanitized, disposable preview and protected workflow dispatch. GitHub source
and database gates alone do not certify that this browser scenario executed.


### KGUI-CARD-STUDIO-01K: server-verified same-tenant dual-principal admission

For the protected `card-studio` scenario, the two sanitized, independently
authenticated Card Studio users must have **distinct user IDs within the same
tenant**. Two users in different tenants would only establish tenant-level
isolation and must not qualify as evidence of owner isolation within a tenant.

The existing `/api/auth/validate-session` endpoint now provides a fresh,
authenticated HTTP 200 server identity for both browser contexts before the
second owner's foreign-read and mutation probes. The test requires the
server's affirmative session-validity envelope, canonical user and tenant UUIDs,
and agreement with the browser's post-login identity. It rejects an unavailable
auth endpoint, mismatched browser/server identity, same user, or different
tenants. This check does not trust a browser-injected identity or introduce
another authorization mechanism. Both users must still independently create
real PostgreSQL-backed templates before negative authorization assertions
count. All prior archive and retry-proof requirements remain unchanged.

The approved preview operator must provision two separate **write-authorized
sanitized users in one disposable tenant** and explicitly authorize the
preview-only mutations. An account in another tenant is not a substitute.
The existing real PostgreSQL test independently covers cross-tenant isolation.
The protected workflow and production default-disabled Card Studio setting are
unchanged. No source-only test proves that the live Chromium trial ran.

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

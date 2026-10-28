# Intelligent Search Consumer Release: SR-01

Status: **RED, source implementation merged; actual signed deployment and acceptance pending**. Source baseline: merged PRs #550 and #559.

## Verified failure

The supplied live consumer session queried "Whats the weather" in General mode and received five Wikipedia sources and twelve ranked passages, including content about the band Weather Report. No actual weather observation or weather-specific clarification was displayed.

## Repo inspection

- `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/hooks/useIntelligentSearch.ts`: starts with `mode: 'general'`, sends selected mode, and clears results on option edits. Invalidates old results by sequence but does not demonstrate transport abortion.
- `src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py`: resolves explicit mode and passes it into InternetCapabilityService. Returns retrieved sources without an answer-synthesis guarantee.
- `src/ai_karen_engine/services/tooling/internet_capability_service.py`: `_resolve_mode()` uses explicit request mode first, then `SearchQueryPlanner.classify_mode()`. Dedicated `mode == 'weather'` observation handling exists. The service explicitly does not own final answer wording.
- `src/ai_karen_engine/services/search/search_query_planner.py`: uses keyword mode detection; lacks weather recognition; keyword `today` routes to news.
- `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/ResultsWorkspace.tsx`: excerpt/source tab-first UX, with fallback wording stating results are not a generated answer.
- `docs/INTELLIGENT_SEARCH_COMPLETION.md`: prior UI/API and mocked Playwright verification documented; live consumer-intent parity not demonstrated.

## Contract to implement

1. Consumer default is automatic intent routing. User-visible search modes are optional advanced overrides.
2. CORTEX owns eligible intent/capability decision. Runtime owns selection validation, policy, prompt construction, model usage, response synthesis, fallback and execution receipts. The plugin only performs governed capabilities, using canonical search/observation services.
3. Don't add another keyword classifier or model call to the search planner, plugin route or React UI. Reuse existing CORTEX, RuntimePolicy, ExpressionGateway and provider registry.
4. For weather, ask for missing location when needed, or resolve an authorized location from user context; do not fabricate conditions.
5. Synthesis may consume retrieved evidence and must cite it. If synthesis unavailable, label excerpts as evidence, not as an AI answer. Preserve degraded reasons for model, tools, persistence and presentation separately.
6. Keep prompt injection from retrieved material untrusted; enforce permissions and tenant isolation at final execution/persistence gates.
7. Present answer first, source cards second, diagnostics under advanced/admin controls. Preserve keyboard, screen-reader and responsive UX.
8. Audit the three search implementation trees for packaging vs active copies before consolidation or deletion.

## Proof matrix

| Scenario | Required result |
| --- | --- |
| What's the weather? | Weather intent, valid observation or location request |
| What's the weather in Detroit today? | Weather observation path, location and update time |
| Weather Report jazz band | General/music retrieval, never weather observation |
| Weather forecasting theory | Informational search rather than current observation |
| Latest weather research | Research/news retrieval with time/source handling |
| User forces advanced mode | Runtime-gated explicit override |
| Observation source unavailable | No fabricated readings; explicit degradation |
| Evidence exists, model unavailable | Labeled source excerpts, no fake answer |
| Search while changing settings | Previous completed result preserved |
| Cancel in flight | Transport abortion where supported; no stale UI overwrite |
| Chat follow-up | Bounded, cited evidence and consistent conversation correlation |
| Saved research across sessions | Durable permitted persistence/replay, tenant-safe |
| Permission denied | Backend rejection; no execution by hidden UI trick |

## Validation commands

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm run test
npm run build
npx playwright test tests/e2e/intelligent-search.spec.ts tests/e2e/intelligent-search-crawl4ai.spec.ts tests/e2e/intelligent-search-stale-response.spec.ts
```

These commands are **required**, not asserted to have passed.

## Release gates

P0: routing, truthful sourced answer, live provider verification, RBAC and provenance. P1: consumer answer-first layout, cancel/state preservation, research continuity, accessible source navigation. P2: comparison templates, source quality analytics and deeper research collections.

Consumer release stays **RED** until real provider + runtime + browser scenarios pass and human verification confirms the workflow. Never equate a green mocked component suite with real consumer readiness.


## Deployment verification update (October 26, 2026)

Repository quality checks were green at b0d4d9dddcfe05409673207fce6ccae2d0bfc63d.
Consumer release remains RED pending authenticated deployment acceptance.

The canonical scripts/ci/verify_deployment_revision.py fails closed for
non-HTTPS or redirected origins, missing or inconsistent revision metadata,
cacheable responses, oversized bodies and malformed JSON. The same verifier
runs before and after browser acceptance, with a final GitHub PR-head check.
All acceptance login scenarios reject unexpected origin redirects.

This is runtime self-reported revision evidence, not independent platform
build attestation. Vercel deployment ID, commit, READY status and immutable
URL must be verified separately. Manual workflow runs on another branch
without these guards are not PR #550 release receipts.


## SR-01 verified deployment topology and independent attestation (October 26, 2026)

**Consumer release: RED; repository checks: green at previous reviewed head.**

### Observed Vercel problem

Vercel project \`ai-karen\` currently selects framework \`python\` at repository root.
The preview built from the reviewed PR head
\`27cc86232b383b82688f068ebefb0247cbdc20a7\`
ended with \`PYTHON_ENTRYPOINT_NOT_FOUND\` and state \`ERROR\`.
This is a concrete project/runtime mismatch, not proof of a Python source defect.
Do not select an arbitrary \`server/app.py\` file or claim consumer readiness
from a superficially successful Python deployment.

### Canonical deployed consumer application

- \`deploy/compose/docker-compose.prod.yml\` owns the supported production
  \`web\` + \`api\` topology. The frontend is a Next.js application rooted at
  \`src/ui_launchers/Karen-AI-Theme\`.
- \`server.mjs\` is the canonical production web ingress and overwrites
  forwarded transport headers before backend proxying. Vercel's native Next.js
  runtime will not execute that custom ingress. A Vercel preview is therefore
  **not automatically equivalent** to the production Docker consumer stack.
- The frontend's API route handlers proxy to the Python backend. Running only
  the frontend with an inaccessible backend may build but cannot pass
  authenticated search, persistence, provider routing or health acceptance.
- Changes to the Vercel project framework/root must not be used as a proxy for
  full-stack release readiness. Preserve environment protection and production
  security requirements; do not publish a reduced-auth release for a green badge.

### Acceptance contract for a Vercel preview

The protected \`search\` workflow executes two **separate** sources of evidence
both before and after the browser tests:

1. \`scripts/ci/verify_vercel_deployment.py\`: independently fetches platform
   deployment metadata using the protected \`VERCEL_TOKEN\` and configured
   \`VERCEL_PROJECT_ID\` and \`VERCEL_ORG_ID\`. Requires a canonical HTTPS
   \`.vercel.app\` immutable deployment URL, project identity, \`git\` source,
   \`READY\` state, nonproduction target, source repository and full reviewed SHA.
2. \`scripts/ci/verify_deployment_revision.py\`: separately fetches the
   running application's non-cacheable, nonredirecting revision endpoint,
   requiring exact SHA parity. It additionally requires a live `/api/health`
   response with `status=ok` and boolean `backend_ready=true` before any
   authenticated browser acceptance; frontend-only previews fail closed.
   Neither observation replaces the other.

The workflow then runs real authenticated user search, source citations,
weather/location and durable replay. A post-test check requires unchanged
platform deployment, running revision and PR head.

**Required protected environment configuration:** \`KAREN_SEARCH_ACCEPTANCE_URL\`
must be the deployment's immutable HTTPS URL; \`VERCEL_PROJECT_ID\` and
\`VERCEL_ORG_ID\` must be protected environment variables; \`VERCEL_TOKEN\`
must be a least-privilege environment secret. Existing acceptance credentials
remain environment secrets, never committed or printed.

A separate provider-specific provenance adapter is required for self-hosted
Docker deployments. Never silently skip independent attestation, fabricate
provider readiness, or mark the consumer release green on frontend-only evidence.

### Proof remaining

- Verify a supported full-stack deployment with working canonical ingress,
  backend /api/health, model execution receipts, persistence and citations.
- Confirm exact deployment attestation and authenticated browser tests.
- Conduct human consumer UX acceptance on the same reviewed release image.


### Protected preview access without credential leakage

The Vercel project enables SSO deployment protection for preview URLs.
The release verification scripts and Playwright tests must therefore
authenticate to the **verified deployment origin** before evaluating the
consumer experience. An SSO login redirect must not count as a healthy app.

- The canonical revision/health verifier accepts a protected
  \`VERCEL_AUTOMATION_BYPASS_SECRET\` only for a validated HTTPS
  single-label \`.vercel.app\` origin. It sends the bypass header on the
  first-party, nonredirecting revision and health requests only.
- Live consumer Playwright uses
  \`e2e/fixtures/verified-vercel-preview.ts\` to obtain a first-party
  \`_vercel_jwt\` cookie via a nonredirecting Vercel protection handshake.
  No bypass credential is put into a URL, global browser headers, a
  request interceptor, stored browser state, or another website request.
- The workflow scopes browser account credentials exclusively to the
  credential-validation and Playwright steps, not checkout, \`npm ci\`,
  Node setup or browser installation. The bypass secret is scoped only
  to revision probes and the protected browser step.
- Configure \`VERCEL_AUTOMATION_BYPASS_SECRET\` as a protected
  \`karen-sanitized-browser-acceptance\` environment secret. Require
  a human reviewer for source revision authorization and keep this
  environment unavailable to untrusted forks/branches. A GitHub
  environment name alone does **not** guarantee required review;
  verify and enforce protection settings in repository administration.
- The history restoration workflow remains a distinct canonical
  deployment acceptance track, without a Vercel-only bypass assumption.

The fixture has no mock responses and no request interception. All
actual user/application interactions continue through the real backend
under normal RBAC and tenant policies. Until the preview is READY and
its runtime metadata and backend are attested, acceptance remains RED.


## Final reviewed-source execution rule (October 26, 2026)

The secret-bearing search browser harness is **post-integration only**.
GitHub workflow dispatch must originate from `refs/heads/main`, and
`target_sha` must equal both `GITHUB_SHA` and the current default-branch
head read from GitHub before source checkout. The same main-head check runs
after browser testing, alongside independent Vercel deployment identity,
the running application's revision, and backend readiness.

The previous approach, checking out the head of PR #550 during a
`workflow_dispatch` from main, is rejected. A dispatch from a trusted
workflow file does **not** make unmerged source code safe to execute with
browser identity credentials. PR #550 source checks stay in ordinary
non-credentialed CI until the feature is integrated into main.

Release flow: approve and integrate source under the canonical security
and feature gates, deploy an immutable sanitized consumer environment from
that exact reviewed main source, attest the platform and live revision,
perform protected authenticated browser acceptance, and promote only a
human-approved production-equivalent build. If an immutable sanitized
deployment with the same main SHA is not available, the acceptance job must
fail closed. A green source CI job is not a release receipt.

The separate security hotfix PR #558 was merged into main as
`33f60a97c050fbe42ca58619941b1286935f4c5e` and its history
default-branch restrictions were reconciled without overwriting this
consumer search attestation. No consumer release approval is implied.


## Canonical Docker source identity and running image attestation (October 26, 2026)

The canonical production Docker Compose overlay now requires
`KAREN_DEPLOYED_COMMIT_SHA` for the **API and web images**, builds them with
that source revision, applies revision-specific local image tags, and
propagates the revision to each running container. The web production
Dockerfile rejects malformed or missing 40-character lowercase revisions
and places the revision on an OCI image label and on the existing
`/api/deployment-revision` runtime response path. The API image carries
the same OCI label.

This fixes an earlier Docker-specific blocker: the live revision route
previously had no guaranteed deployed SHA outside Vercel.

### Authorized production host verification

`scripts/ci/verify_docker_release.py` is a separate, read-only verifier
for an operator-controlled Docker host. It expects the exact reviewed SHA
and **both approved immutable Docker image IDs**, sourced from a separately
verified build receipt:

- `TARGET_SHA`
- `KAREN_EXPECTED_WEB_IMAGE_ID` (full `sha256:` image ID)
- `KAREN_EXPECTED_API_IMAGE_ID` (full `sha256:` image ID)
- `KAREN_RELEASE_REPO_ROOT` (trusted checkout with production Compose files)

The verifier calls the canonical Compose services `web` and `api`
without a shell, identifies exactly one running container for each,
requires healthy Docker status, confirms Compose service identity, and
compares live container image IDs, inspected image IDs, OCI revision
labels and runtime SHA against the approved values. It never logs
container environments, authentication secrets or raw Docker inspect
payloads. CI tests cover missing, duplicate, mismatched and unhealthy
containers.

**Important limitation:** SHA-based tags and OCI labels are self-claims.
Checking a Docker image ID against an externally approved digest
detects deployed-image drift, but does **not** independently prove that
an untrusted image builder used the claimed Git source. The release
process must independently attest and approve the build source/image
relationship, protect the build artifacts, and furnish reviewed image
IDs. Never manufacture this approval from the image's own labels.

This Docker verifier is not a substitute for the separately checked
`/api/deployment-revision` and `/api/health` endpoints or for the
authenticated search/replay and human consumer checks. Running this
verifier on the build runner without the actual release containers
is **not** live consumer acceptance.

The Vercel preview workflow remains provider-specific and may not be
used to claim a canonical Docker release. Production promotion stays
RED until the complete deployment, runtime, browser and security
evidence chain is independently confirmed.


## Cryptographically signed Docker release candidates

The canonical `web` and `api` container images can now be published as
**signed, nonpromoted candidate artifacts** using
`.github/workflows/karen-consumer-image-provenance.yml`. This workflow has
no automatic trigger. It must be manually dispatched from the exact current
`main` revision and executes under the separate
`karen-consumer-release-build` GitHub environment.

Before operator use, repository administrators must configure that
environment with **required human reviewers and branch restrictions**.
The workflow's `environment:` field alone does not establish approval.

Each candidate build:

1. Rechecks the actual current `main` SHA before checkout/build.
2. Builds the existing canonical API Dockerfile and production Next.js
   Dockerfile with that SHA, without changing either image implementation.
3. Publishes to the repository-owned GHCR namespace under a SHA-qualified
   candidate tag, and records its **immutable OCI manifest digest**.
4. Signs each digest via `actions/attest@v4`, which uses GitHub OIDC/Sigstore
   artifact attestation and binds the image to source and signing workflow.
5. Independently verifies each artifact against the expected source SHA,
   `refs/heads/main`, exact signer workflow, GitHub repository and attested
   OCI digest using `gh attestation verify`. Rechecks `main` afterwards.

Publication is not deployment, activation, release approval or evidence that
the backend is available to consumers. An attestation for the image manifest
is *not* an OCI config image ID; these are different hashes.

On an authorized deployment host, first authenticate to GHCR, approve both
signed candidate **digest-pinned** image references and corresponding local
Docker config image IDs, and pull the images by immutable digest. Then set:

- `TARGET_SHA`: reviewed, full lowercase commit SHA
- `KAREN_RELEASE_REPOSITORY`: exact case-preserving GitHub `owner/repository`
  identity (e.g. `agustealo/AI-Karen`); GHCR subject paths use lowercase
- `KAREN_SIGNED_API_IMAGE_REF` and `KAREN_SIGNED_WEB_IMAGE_REF`:
  exact `ghcr.io/owner/repository-{api,web}@sha256:...` registry references
- `KAREN_EXPECTED_API_IMAGE_ID` and `KAREN_EXPECTED_WEB_IMAGE_ID`:
  separately approved, complete `sha256:...` *config image IDs*
- `KAREN_RELEASE_REPO_ROOT`: trusted checkout containing the canonical
  production Compose configuration and its separately supplied secrets

The existing `scripts/ci/verify_docker_release.py` CLI now verifies both
GitHub/Sigstore attestations using the trusted GitHub repository, signer,
source commit and `main` source ref. It also requires the digest-pinned
registry reference to exist among each local image's RepoDigests and checks
the approved local image ID. Only then does it execute the existing
read-only running-container proof, requiring both healthy, correctly
labeled Compose services.

**Fail closed:** a missing signature, wrong source, untrusted workflow,
mutable tag, absent image, mismatched digest or config ID, unhealthy
container or changed runtime source revision blocks acceptance. The
verifier does not call `docker pull`, restart containers, upload secrets
or create a deployment. It assumes the host has independently approved
and pulled the immutable artifacts.

Complete consumer release still requires a configured production-equivalent
host, verified HTTPS ingress, live backend health and model/provider
execution, authenticated search/replay, tenant isolation, persistence,
and human UX sign-off. The previous Vercel Python/Next.js mismatch and
Vercel rate limits cannot be bypassed using signed Docker candidates.


### Production Compose must use the signed-image override

Use the **canonical** base and production overlays, followed by the minimal
`deploy/compose/docker-compose.signed-release.yml` override. The override
only replaces `api`/`web` image references with approved digest-pinned
GHCR subjects and removes the local `build` sections using
`!reset null`; it does not copy or reimplement service settings, auth,
RBAC, ports, memory, model routing or observability.

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml \
  -f deploy/compose/docker-compose.prod.yml \
  -f deploy/compose/docker-compose.signed-release.yml \
  config
```

Supply `KAREN_SIGNED_API_IMAGE_REF` and `KAREN_SIGNED_WEB_IMAGE_REF`
from the separately approved signed build receipt and make sure those exact
digest-pinned images are already pulled and running. Never run a
`docker compose up --build` promotion for an attested release, or silently
fall back to images compiled from mutable host source. The verifier checks
the same three-layer Compose service configuration and the running image
identity, but does not create or deploy containers.


## Live signed-Docker consumer ingress verification

A signed image is not an operational consumer application. The existing
`scripts/ci/verify_docker_release.py` CLI now performs the complete,
read-only identity and ingress proof on an authorized deployment host:

1. Validate the **approved** `KAREN_BASE_URL` as a clean HTTPS origin with
   no userinfo, path, query, fragment or nonstandard port before any Docker
   or GitHub calls. The URL must identify the real public web ingress, not a
   build runner or Docker daemon endpoint.
2. Verify the API and web GHCR Sigstore attestations against the exact source
   revision, GitHub repository and signing workflow.
3. Verify the digest-pinned OCI registry manifests and approved image config
   IDs against the actual running healthy Compose services, reusing the
   canonical three-layer production service configuration.
4. Query the public `/api/deployment-revision` endpoint through HTTPS,
   requiring a nonredirecting, uncached `200 application/json` response
   with exactly the reviewed source SHA.
5. Query the public `/api/health` endpoint through the same approved HTTPS
   ingress and require `200 application/json` with
   `status=ok` and `backend_ready=true`.

The CLI requires the existing signed-artifact variables plus
`KAREN_BASE_URL` and fails closed if *any* gate rejects the live runtime.
It deliberately does not use Vercel automation-bypass credentials: the
Docker full-stack ingress must be independently accessible to the authorized
host. The CLI does not alter deployment state, fetch source, run untrusted
user scripts, or read end-user credentials.

**Important:** A public health check is necessary but not sufficient for
consumer approval. After this proof, run the protected authenticated
search/replay test against the same approved immutable revision and repeat
the provenance, revision and backend checks. Human acceptance and
authorization boundaries remain required. The current browser search
workflow is Vercel-specific and must not be misrepresented as a Docker
acceptance workflow until a Docker-capable protected harness is implemented
and independently verified.


## Signed-Docker protected browser acceptance (post-integration only)

The existing `KAREN Browser Acceptance` manual workflow supports a third
`docker-search` scenario in addition to its unchanged `history` and Vercel
`search` scenarios. The Docker scenario shares the *same authenticated*
`intelligent-search-replay.spec.ts` search/citation/weather/persistence
suite and the existing sanitized browser environment. There is no second
search UI test suite, fake answer, or client-side release authority.

**Required operator setup, not verified by source CI:**

- Protect the `karen-sanitized-browser-acceptance` environment with required
  reviewers, approved `main` deployment branches, and sanitized-only test
  credentials `KAREN_UX_EMAIL` / `KAREN_UX_PASSWORD`.
- Register an operator-controlled, dedicated trusted **Linux x64** GitHub
  Actions runner with the `karen-consumer-release` label, access to the
  approved production Docker daemon and read-only GHCR attestation
  verification. This runner must not be shared with untrusted pull requests.
- Configure approved environment variables `KAREN_DOCKER_RELEASE_REPO_ROOT`
  (absolute operator-controlled host checkout directory at the exact
  approved commit), `KAREN_DOCKER_SEARCH_ACCEPTANCE_URL` (clean HTTPS public
  origin), `KAREN_SIGNED_API_IMAGE_REF`, `KAREN_SIGNED_WEB_IMAGE_REF`
  (signed GHCR manifest digest refs), and
  `KAREN_EXPECTED_API_IMAGE_ID` / `KAREN_EXPECTED_WEB_IMAGE_ID`
  (independently approved local Docker image IDs).
- Keep `.env.production` on the authorized host, outside source control.
  Never upload it to GitHub Actions artifacts or put production credentials
  into repository variables or Playwright configuration.

**Execution:** dispatch the existing
`.github/workflows/karen-history-browser-acceptance.yml` from the
current `main` branch, choose `docker-search`, and provide the exact
40-character current `main` SHA as `target_sha`.

The mandatory job sequence is:

1. **Docker host before:** on the trusted Linux release runner, check exact
   `main` SHA and current default branch; attest the on-host checkout and
   compare its three Compose definitions byte-for-byte with the reviewed
   checkout. Call the *existing* read-only signed Docker verifier, checking
   GHCR source/signature, digest-pinned image IDs, running API/web health,
   canonical public HTTPS revision and backend readiness.
2. **Browser replay:** only after the host gate succeeds, use a separate
   GitHub-hosted Ubuntu runner to repeat the public revision/backend
   checks, install pinned npm/Playwright dependencies **without login
   credentials in those steps**, then inject sanitized login credentials
   exclusively into the existing Playwright search/replay execution. The
   shared fixture enforces the approved origin and forbids any Vercel
   bypass secret or bypass-cookie request on Docker.
3. **Docker host after:** only after the browser test and its revision/main
   recheck succeed, run the exact signed-host verification again, confirming
   the approved images, services and HTTPS ingress remain live.

No Vercel project/automation bypass token is used on this path.
No `npm ci`, browser installation, user credentials, uploaded traces,
screenshots, recordings or page-generated scripts execute on the
production-capable Docker runner. No Docker build, pull, deploy or
promotion occurs in any acceptance job.

**Boundary:** these gates prove the approved image identities and observed
running browser behavior before/after the test, not atomic protection
against an unobserved deployment switch mid-test. Enforce deployment
immutability, host/network controls and release change freeze outside the
test workflow. This workflow also does not authorize a consumer launch:
signed-image build/host approvals and human UX/security sign-off remain
independent requirements.

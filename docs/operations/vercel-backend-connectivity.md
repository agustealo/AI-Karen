# Vercel frontend to canonical AI-Karen backend

**Owner:** Deployment and runtime configuration. The Next.js frontend does not host
or emulate Karen's Python/FastAPI runtime.

## Deployment topology and source of truth

Karen's canonical backend is the FastAPI app in
`src/ai_karen_engine/app.py`. Its required-dependency readiness authority
is `GET /ready` in
`src/ai_karen_engine/api_routes/monitoring/probes.py`; it requires
configuration and PostgreSQL availability. Optional model/provider degradation
does not by itself make PostgreSQL-backed consumer state ready.

Local/Docker installs use the Compose service name `http://api:8000` *within
the Docker network*. That hostname, `host.docker.internal`, localhost and
loopback addresses **cannot serve as an ordinary Vercel function's backend**
because Vercel runs in a separate network. A READY Vercel Next.js deployment
only proves compilation and static/web-function deployment, not backend access.

For Vercel Preview and Production, configure the existing server-only
`KAREN_BACKEND_URL` environment variable to the **actual, separately deployed,
network-reachable canonical FastAPI origin**. Use HTTPS for internet-routed
backends, TLS verification and server-side authentication; a deliberately
private, routed deployment must have its own verified private connectivity.
Never substitute `NEXT_PUBLIC_*`, `API_BASE_URL`, `BACKEND_URL`, or arbitrary Docker
fallback URLs for this authority. The `BACKEND_URL` alias is accepted only
outside hosted Vercel environments for local compatibility. In Vercel,
an absent `KAREN_BACKEND_URL` fails closed even if `BACKEND_URL` is set. Do not place usernames, tokens, credentials,
path suffixes or query parameters inside the backend-origin setting.

The backend requires its own deploy, networking, PostgreSQL and provider
runtime. Vercel's Next.js deployment does not start a local FastAPI process,
PostgreSQL container or local model server. Do not disable authentication,
publish a raw database connection, or create fake model responses to turn
a connectivity failure into HTTP 200.

## Existing API image and production deployment safety

The repository already builds the canonical FastAPI image with the root
`Dockerfile` (`--target app --build-arg PROFILE=runtime`). Its entrypoint is
`python -m uvicorn ai_karen_engine.app:create_app --factory --host 0.0.0.0 --port 8000`.
The existing `Production First-Boot Smoke` workflow builds that image and
runs `scripts/ci/production-first-boot-smoke.sh` against isolated PostgreSQL
and Redis containers. This is a **short-lived CI boot proof**, not a deployed
public API endpoint or proof of a persistent model-serving backend.

**Use the existing canonical production overlay at `deploy/compose/docker-compose.prod.yml` when deploying the Compose stack.** It is layered on top of the root Compose file with `-f docker-compose.yml -f deploy/compose/docker-compose.prod.yml`, requires `KAREN_DEPLOYED_COMMIT_SHA` and production secrets, overrides inherited development environment files and published ports, and removes mutable application source mounts. It still requires an operator-provided persistent host, PostgreSQL, TLS ingress, correctly governed secret storage, and successful `/ready` verification. The overlay does not provision hosting or a public backend address.

**Do not deploy the root `docker-compose.yml` alone as production configuration.**
Its `api` service explicitly specifies development mode, debugging, local
database addresses and development database credentials. Those settings can
override values from `.env`. Likewise, the smoke harness contains
test-only credentials and must never be used to provision real consumers.

Deploy the existing API image on an operator-owned persistent host with
production settings supplied through a protected secrets facility, an
isolated PostgreSQL database with required migrations, Redis, durable state,
TLS termination, and verified provider connectivity. Restrict inbound
access to authenticated application traffic, and verify an actual
`GET /ready` response **from the Vercel function network** before binding
the hosted frontend. Do not copy any CI smoke passwords, local database URLs,
development auth bypasses or test-only certificates into the real environment.

## November 1, 2026 incident: evidence and resolution gate

- Exact-head Preview `35e948babe67e314a3280f47702c73e0db31a678`
  served `/api/deployment-revision` at 200 but `/api/health` at 502.
- A later diagnostic Preview logged
  `target_scope=loopback`, `configuration_source=default`,
  `cause_code=ECONNREFUSED` for `GET /ready`. This is proof the
  **deployed Vercel function was not receiving a usable configured backend
  origin** and attempted its local default instead.
- A Vercel project environment-variable *entry* named `KAREN_BACKEND_URL`
  is not proof the function received a nonempty value. Sensitive values are
  not printed, disclosed or inferred from redacted connector responses.
- The checked production frontend also returned HTTP 502 for health. The
  preview log identifies the preview's root cause; the older production
  deployment's complete target configuration has not been independently proven.

The Vercel proxy now fails closed with a structured configuration error for a
missing, invalid, insecure or Docker-only origin rather than attempting its
loopback default. This diagnostic **does not deploy the missing backend**.

## November 18, 2026: Vercel frontend credential ownership gate

A read-only Vercel metadata audit of the existing `ai-karen` Next.js project
observed 101 variable records, including **100 sensitive entries targeting
both Production and Preview**. The inventory includes backend authentication
signing, PostgreSQL, Redis and Hugging Face token variable names. No secret
values were retrieved. This does not prove the contents are valid production
credentials or that any credential was accessed by a preview deployment.

The frontend is a Next.js transport/proxy, not the FastAPI auth, database,
model-acquisition or inference owner. Direct inspection of the 23 frontend API
route source files, the auth helper and the server-side backend proxy found
no direct dependency on the listed backend-owned credentials. Imported
dependencies and a complete deployment are still independent verification
boundaries.

**Correct the existing environment before consumer preview acceptance:**

1. Inventory the actual frontend and backend service requirements without
   printing or exporting credential values. Restrict the Vercel project to
   frontend-required settings such as its approved server-only
   `KAREN_BACKEND_URL`; retain credentials with the canonical backend.
2. Remove backend-owned variables from **both** Vercel Production and Preview
   configurations only after confirming the backend retains its separately
   provisioned credentials. Do not copy credential values to the browser or
   `NEXT_PUBLIC_*` names. If an actual secret is believed exposed, rotate it
   at its issuing authority and propagate via governed secret management.
3. Run the existing protected GitHub Actions workflow
   `Vercel Frontend Environment Boundary` with the **exact reviewed main
   SHA**. The workflow is `workflow_dispatch` on `main`, uses the
   `beta-release` environment, and performs *read-only* Vercel
   `GET /v10/projects/{idOrName}/env?decrypt=false`. It checks the entire
   paginated metadata inventory, never requests decrypted values and never
   changes the project. The protected environment must supply
   `VERCEL_TOKEN`, `VERCEL_PROJECT_ID` and `VERCEL_ORG_ID`.
4. Require the boundary inspection to pass before the next credentialed
   frontend acceptance. Independently verify the latest immutable deployed
   frontend commit and backend `GET /ready`; a passing environment scope
   inspection is **not** evidence of backend or native-model readiness.

The canonical inspection owner is
`scripts/ci/verify_vercel_environment_scopes.py`, with offline regression
tests in `tests/architecture/test_vercel_environment_scopes.py`.
Source CI exercises its boundary contract without Vercel credentials.
The on-demand protected workflow audits *real* project metadata. The
verifier admits only explicit reviewed frontend-owned settings, including
an exact allowlist of browser-visible `NEXT_PUBLIC_` names. There is no
prefix-based exception. Unknown application variables, case-variant or
credential-like public keys, hidden production inventory, malformed scope,
pagination ambiguity, inaccessible platform, or backend credentials present
in the frontend all block live inspection. This is a metadata ownership gate,
not a replacement for code review or independent preview build inspection.

## Operator verification

1. Verify the real FastAPI host is running and its `GET /ready` answers
   HTTP 200 with `ready: true`, `status: ready`, and components
   `configuration: ready` and `database: ready`. A generic monitoring
   `/api/health` response, even at HTTP 200, is not sufficient.
2. Verify the chosen origin is reachable **from the Vercel serverless
   network**, not merely from a Docker container or developer machine. Keep
   transport encrypted and protect the backend from unauthorized requests.
3. In the `ai-karen` Vercel project's environment settings, supply the
   exact server-only `KAREN_BACKEND_URL` for the intended Preview and
   Production targets. Confirm the right branch-specific overrides and
   redeploy to get a new immutable deployment with those values.
4. On that exact immutable deployed URL, independently verify
   `GET /api/deployment-revision` reports the reviewed full Git commit,
   and `GET /api/health` returns HTTP 200 with exactly
   `{"status":"ok","backend_ready":true}` and `Cache-Control: no-store`.
   Any 503, 502 or redirect blocks acceptance.
5. Only then run the existing protected `copilotkit-consumer` Playwright
   acceptance on the reviewed exact revision. It must prove real model
   execution, provenance, Stop/cancellation, saved drafts, rendered replies,
   restored history, and no disabled inspector-chunk loads.
6. Review Vercel runtime logs for `canonical_upstream_unavailable`,
   `target_scope`, `configuration_source`, and a sanitized `cause_code`.
   The diagnostic deliberately excludes actual URLs and secret values.

**Release rule:** Docker first-boot smoke, Vercel READY state and GitHub quality
gates are separate from live backend and authenticated browser acceptance.
A consumer release must not pass while any of these independent live checks
fails. Never broaden deployment protection or replay a mutating chat request
against an alternate host to work around missing backend connectivity.

## November 23, 2026: KREADY-01A production identity and consumer acceptance

**Latest observation: production *platform metadata* matches GitHub `main`; live consumer acceptance remains NO-GO until proven.** This is a timestamped evidence record, not an authorization to deploy or promote.

### Deployment transition observed during this audit

1. At the start of the audit, GitHub `main` was `573dea8e3104d8b5e1d429058917c868c13aaf7b` (PR #1262). Main Quality Gate, Production First-Boot Smoke, Context Authority Contract and Cognitive Proof CI had succeeded, but the Vercel combined commit status was failure and an exact-SHA deployment lookup returned no result. The older production deployment `dpl_6civMQw1LWrEZGcy8NsUppZp9Yfz` was READY for `fbfea8f639252b9bd345b78546f2bbbba6d7b41d` (PR #1270).
2. During inspection, `main` advanced through an unrelated database configuration PR to **`7c5369b68ff7cbbf4286cfb01b068a9ba89250b8`**. Vercel subsequently reported production deployment **`dpl_AevQLfM6K569mdLrKhkmrXeRtiVo` READY** with `githubCommitRef=main` and **exact matching `githubCommitSha=7c5369b68ff7cbbf4286cfb01b068a9ba89250b8`**. The live production aliases reported for this deployment were `ai-karen-beta.vercel.app` and `ai-karen-zeustheeternal-3982.vercel.app`. The GitHub Vercel combined commit status for `7c5369b` was success.
3. **Resolution scope:** The earlier Vercel *platform source mismatch* is no longer a current blocker for `7c5369b`. **Not resolved:** independent proof of the runtime's `/api/deployment-revision` response, the Vercel function's connection to canonical FastAPI `GET /ready`, environment variable ownership, signed-in browser acceptance, model execution, and independent reviewer approval. Neither the Vercel READY state nor absence of recent runtime logs establishes them.
4. A follow-up exact-head Main Quality failure exposed a legacy conversation adapter importing a removed ID helper alias. PR [#1272](https://github.com/agustealo/AI-Karen/pull/1272) corrected that import to the existing canonical `coerce_user_id` owner and added tenant-scope regression tests. After Main Quality, real Production First-Boot, Chat System Burn and live PostgreSQL workflow proofs passed, #1272 squash-merged at `127da9e5ddc9709458e932c16a82ad42bebf1f02`. This is integration evidence, not production acceptance.
5. A **read-only, non-decrypted Vercel environment inventory** found **101** frontend project variable records: **94** names are outside the exact approved `FRONTEND_ENV_KEYS` set maintained by `scripts/ci/verify_vercel_environment_scopes.py`, including seven explicitly listed backend-only keys (authentication signing, database, Redis and model-access credentials). Names and target scopes were evaluated; no secret values were requested. Because these records target Preview and Production, the existing protected frontend environment boundary must remain a **release blocker**. Do not delete or move settings before independent backend credential ownership has been verified.

### Reuse the existing, fail-closed release gate

1. Pin the **current reviewed 40-character main SHA**. Inspect the actual immutable deployment target, Vercel project ID, deployment ID, source SHA and production aliases. Revalidate after tests to prevent source drift; do not automatically promote a preview or silently accept an older alias.
2. After operator-governed frontend credential-scope remediation, execute `.github/workflows/vercel-environment-boundary.yml` with the matching SHA, using the existing read-only `scripts/ci/verify_vercel_environment_scopes.py`. Do not request decrypted values, disclose credentials or remove backend-owned credentials before verifying separately provisioned backend ownership.
3. On the exact approved immutable deployed hostname, run `scripts/ci/verify_vercel_deployment.py` with `KAREN_VERCEL_ACCEPTANCE_TARGET=production` (or expressly approved `preview`), followed by `scripts/ci/verify_deployment_revision.py`. Require actual `/api/deployment-revision` SHA parity, `/api/health` successful backend readiness and canonical FastAPI `GET /ready` reached from the web runtime network. Source/CI boot tests do not substitute.
4. Run the existing protected `.github/workflows/karen-history-browser-acceptance.yml`, including the authorized `copilotkit-consumer` and failure/replay scenarios, on that immutable deployment. Use isolated tenant-scoped test identities and preserve secret-free evidence. Revalidate Vercel platform metadata, serving application and `main` after the browser run.
5. Record exact CI run IDs, deployment ID, sanitized backend readiness proof, browser outcome, independent reviewer decision and rollback candidate. Any missing gate means **NO-GO for consumer release**.

**Governance observation:** At the audit time, GitHub `main.protected` was `false` and the rulesets listing was empty, while the direct protection endpoint returned 403 to this integration. An administrator must independently verify mandatory check and reviewer enforcement; do not infer secure protection settings from successful CI alone.

**Authority:** Release scripts, protected workflows, Vercel platform source, runtime responses and verified browser receipts own the decision. This dated documentation cannot certify production readiness or justify a duplicate orchestrator, provider fallback, UI readiness flag or deployment script.

Evidence: [old main](https://github.com/agustealo/AI-Karen/commit/573dea8e3104d8b5e1d429058917c868c13aaf7b), [new main](https://github.com/agustealo/AI-Karen/commit/7c5369b68ff7cbbf4286cfb01b068a9ba89250b8), [older Vercel production](https://vercel.com/zeustheeternal-3982/ai-karen/6civMQw1LWrEZGcy8NsUppZp9Yfz), [matching Vercel production](https://vercel.com/zeustheeternal-3982/ai-karen/AevQLfM6K569mdLrKhkmrXeRtiVo).

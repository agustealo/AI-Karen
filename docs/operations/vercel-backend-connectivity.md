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

## November 23, 2026: KREADY-01A exact-production-revision hold

**Status: NO-GO for latest-main consumer acceptance; release of another build is not authorized by this audit.** This is an observed deployment/provenance gap, not evidence that the current production deployment is offline.

| Evidence source | Observed fact |
| --- | --- |
| GitHub branch `main` | `573dea8e3104d8b5e1d429058917c868c13aaf7b`, PR #1262 merged |
| Latest-main Actions | Main Quality Gate, Production First-Boot Smoke, Context Authority Contract and Cognitive Proof CI succeeded for this exact SHA |
| GitHub combined commit status | Vercel reported failure, linking to the deployment build-rate-limit guidance |
| Vercel production deployment | `dpl_6civMQw1LWrEZGcy8NsUppZp9Yfz`, READY, Git SHA `fbfea8f639252b9bd345b78546f2bbbba6d7b41d` (PR #1270) |
| Production aliases on that deployment | `ai-karen-beta.vercel.app`; `ai-karen-zeustheeternal-3982.vercel.app` |
| Exact Vercel deployment lookup for latest `main` | No matching deployment returned |
| Authenticated end-to-end browser acceptance for latest `main` | Not observed; do not infer from source CI or static Vercel READY |
| Runtime health from live browser-network requests | Not independently verified in this audit environment |
| Independent release approval | No approval submission observed on PR #1262 |

**Authority boundary:** The current production deployment is valid as a separate deployed artifact, but it is not proof that the later `main` changes have been deployed and accepted. The previously documented Vercel frontend environment-variable ownership and canonical FastAPI backend readiness gates remain independent and unresolved until rerun with live evidence. Absence of errors or available logs is not health proof.

### Reuse the existing release gate

1. Pin a reviewed **40-character** GitHub `main` commit and inspect the immutable Vercel deployment metadata, target, project ID and source SHA. If `main` advances during testing, restart the evidence run on the new head. Do not automatically promote a preview or substitute an older production alias.
2. After operator-governed frontend credential scope remediation, run `.github/workflows/vercel-environment-boundary.yml` against the exact `main` SHA. Only the existing `scripts/ci/verify_vercel_environment_scopes.py` owns this check. Never request decrypted secrets or move backend-only credentials into frontend Preview or Production.
3. On an explicitly approved immutable deployment hostname, run `scripts/ci/verify_vercel_deployment.py` with the matching `KAREN_VERCEL_ACCEPTANCE_TARGET` and `scripts/ci/verify_deployment_revision.py`. Demand matching platform metadata, running `/api/deployment-revision` identity and live `/api/health` backend readiness, followed by direct canonical FastAPI `GET /ready` verification from the web runtime network. A first-boot container test or frontend compile does not satisfy these checks.
4. Execute the **existing protected** `.github/workflows/karen-history-browser-acceptance.yml` on that reviewed SHA, including the authenticated `copilotkit-consumer` flow and required failure/replay scenarios, using disposable tenant-scoped identities. Keep acceptance credentials, conversation content and traces private. The workflow's pre-/post-browser provenance checks are mandatory, not optional.
5. Record sanitized proof links for exact GitHub run IDs, immutable Vercel deployment ID and commit, backend readiness response, authenticated browser results, independent review decision and rollback candidate. Missing evidence means **NO-GO**, not a green approximation.

**Administrative follow-up:** GitHub branch metadata reported `main.protected=false`, and a repository rulesets query returned no enforced rulesets. A separate branch-protection endpoint returned 403 for this integration. An administrator must verify the actual mandatory CI/review enforcement before declaring release governance complete; this audit does not claim the integration has administrative access.

This section is a dated observation. The acceptance source of truth remains the existing release scripts, workflows, deployment metadata and runtime receipts, not this document. Do not create new deployment orchestrators, provider fallbacks, or UI-owned readiness flags.

Evidence links: [main commit](https://github.com/agustealo/AI-Karen/commit/573dea8e3104d8b5e1d429058917c868c13aaf7b), [main quality](https://github.com/agustealo/AI-Karen/actions/runs/45206385059), [first boot](https://github.com/agustealo/AI-Karen/actions/runs/45206385175), [older READY production artifact](https://vercel.com/zeustheeternal-3982/ai-karen/6civMQw1LWrEZGcy8NsUppZp9Yfz).

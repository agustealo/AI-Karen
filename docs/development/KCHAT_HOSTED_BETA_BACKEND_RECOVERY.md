# KCHAT hosted beta backend recovery and consumer-release gate

## Purpose and scope

This is an operational recovery contract for the **existing** AI-Karen hosted
beta infrastructure. It does not authorize the creation of another backend,
database, Redis instance, provider router, or frontend connection. The
canonical API and model execution must remain owned by Karen's authenticated
runtime; Vercel hosts the Next.js consumer ingress only.

Last reviewed against connected accounts: **2026-11-04**.
Recorded evidence is a point-in-time observation, not current availability.

## Verified inventory and failure evidence

| Responsibility | Existing resource | Observed state |
| --- | --- | --- |
| Source | `agustealo/AI-Karen` | Main includes the native ChatRuntime streaming and immediate-Enter acceptance fixes |
| Consumer frontend | Vercel project `ai-karen`, ID `prj_uAqBwgpUsdA0OEoomX4klWUYEWyg` | Production deploys can be READY while API calls fail |
| Canonical beta API | Render `ai-karen-beta-api`, ID `srv-dbjmh78u01pc73ftse40` | Existing service tracks `feat/chat-consumer-conversation-management-20261031`, auto-deploy disabled |
| API origin | `https://ai-karen-beta-api.onrender.com` | Not verified healthy; do **not** route consumers here yet |
| Database | Render `ai-karen-beta-postgres`, ID `dpg-dbjme1tg1s2s7385svhg-a` | Existing Postgres reports available |
| Redis | Render `ai-karen-beta-redis`, ID `red-dbjme2ijnfac738ehstg` | Existing Key Value reports available |
| Render deployments | `dep-dbjmh7gu01pc73ftsg10`, `dep-dbjro5nlk1mc73a499u0`, `dep-dbjt05nlk1mc73a7ftig` | All reported `update_failed` on November 1 |
| Vercel runtime | `/api/auth/[[...path]]` | 55 canonical backend configuration errors in the sampled 24-hour window |

The Render container image **built successfully**, but the Python API
crashed during import before opening an HTTP port. The last recorded
exception was:

`RuntimeError: Missing required environment variables in production`

The missing variables listed by the running application were:
`KARI_DUCKDB_PASSWORD`, `KARI_JOB_ENC_KEY`,
`KARI_JOB_SIGNING_KEY`, `KARI_MODEL_SIGNING_KEY`,
`SECRET_KEY`, `AUTH_SECRET_KEY`, `DATABASE_URL`,
`POSTGRES_URL`, `AUTH_DATABASE_URL`, `REDIS_URL`,
`EXTENSION_SECRET_KEY`, and `EXTENSION_API_KEY`.

This list comes from the real import failure. Its single canonical source
is `required_env_vars` in
`src/ai_karen_engine/server/config.py`. Update **that** owner when the
production runtime contract changes. Do not create an independent second
production secrets registry.

## Ownership and recovery order

### 1. Keep the existing Render resources; correct live branch provenance

The only supported deployment branch for new beta releases is `main`.
The checked-in Blueprint `deploy/render/render.yaml` now names `main`.

The live Render service has a separate stored branch setting. Blueprint
editing does **not** update that setting. It must also be switched to
`main` under the existing `ai-karen-beta-api` service before starting
a new reviewed deployment. Leave auto-deploy disabled while this release
is unproven. Do not create or apply a second Blueprint: Render may create
suffixed duplicate resources instead of adopting these existing ones.

Use the actual `main` SHA as the deployment source receipt. A deployment
from the obsolete feature branch cannot prove the current consumer.

#### Existing-service branch reconciliation (protected workflow)

The checked-in Render Blueprint is desired source configuration. Existing
Render services have independent live settings. A reviewed main commit can now
use [Render Beta Service Reconcile](../../.github/workflows/render-beta-service-reconcile.yml)
to inspect or repair **only** the existing API's Git branch and manual-deploy
policy. This route uses Render's official PATCH service endpoint:
https://api-docs.render.com/reference/update-service .

Configure the existing GitHub Actions protected `beta-release` environment
with `RENDER_API_KEY` as a **secret** and the following **nonsecret variables**:
`RENDER_BETA_SERVICE_ID=srv-dbjmh78u01pc73ftse40` and
`RENDER_BETA_WORKSPACE_ID=tea-dbjm53o473hc73a8s5ng`.
Use a least-privilege, authorized Render API key, and never commit, log,
copy into issues or return its value.

1. Choose the `main` branch in the workflow-dispatch UI.
2. Supply the **exact current reviewed 40-character main SHA**.
3. Run `inspect` first. A detected mismatch intentionally fails without mutation.
4. After confirming the existing Render identity and reviewed revision, run
   `apply` with the same current SHA. The workflow verifies GitHub main
   has not moved, the Render service ID, owner, name, repo and type match
   the checked-in Blueprint, and updates **only** `branch: main` and
   `autoDeployTrigger: off`. It GET-verifies the result.
5. Confirm service branch and manual deployment in the existing Render
   Dashboard. The workflow **does not** deploy, create resources, set
   secrets, edit environment groups, rotate keys, or change Vercel.

Do not run a new API deploy until the required production environment is
properly configured. The GitHub workflow deliberately refuses to treat a
source update as a successful backend deployment. The script is reusable
locally through Python's standard library for an authorized operator, and
its safety contract is tested in
`tests/architecture/test_render_beta_service_reconcile.py`.

### 2. Establish real Render production settings without copying secrets into git

Configure the missing keys in the **existing** service's protected
environment settings. Never put credentials, generated values, connection
strings, session cookies, API keys, or encryption material in an issue,
PR, log, screenshot, chat, or committed `.env` file.

Reuse the existing PostgreSQL connection from `ai-karen-beta-postgres`
for `DATABASE_URL`. Set `POSTGRES_URL` and `AUTH_DATABASE_URL`
to the same authorized database identity using the
`postgresql+asyncpg://` scheme required by SQLAlchemy's async engine.
Do not infer or substitute a database address, and do not treat
`postgresql://` as an async driver URL.

Reuse the existing `ai-karen-beta-redis` internal connection for
`REDIS_URL`. The signing and authentication keys must be freshly and
cryptographically generated by the approved secret manager or deployment
environment. `KARI_JOB_ENC_KEY` is format-sensitive: generate valid
Fernet-compatible key material, not an arbitrary generic random string.
Do not rotate a populated job-encryption key without a re-encryption or
recovery plan.

`KARI_CORS_ORIGINS` must contain the exact trusted deployed consumer
origin, not `*`. All development bypass variables defined in the
Blueprint must remain disabled, and production configuration validation
must remain fail-closed. Never make startup green by changing
`ENVIRONMENT` to development or inserting the development defaults.

#### Protected read-only environment preflight

The existing [Render Beta Service Reconcile](../../.github/workflows/render-beta-service-reconcile.yml)
workflow supports the explicitly selected `inspect-env` mode. Keep the same
protected `beta-release` environment and `RENDER_API_KEY` secret, and add
these nonsecret protected variables for the **existing** resources:

- `RENDER_BETA_POSTGRES_ID=dpg-dbjme1tg1s2s7385svhg-a`
- `RENDER_BETA_KEY_VALUE_ID=red-dbjme2ijnfac738ehstg`

Dispatch on the reviewed `main` branch with its exact 40-character SHA
and `mode=inspect-env`. The mode **only reads** service, PostgreSQL, Key
Value, direct environment variables, environment-group inventory and
internal datastore connection metadata using Render's official API.

It verifies workspace/owner, existing resource IDs, names, region,
availability and private connection schemes; reads the actual mandatory
variable names from the source-of-truth `required_env_vars` declaration
in `src/ai_karen_engine/server/config.py`; and checks Fernet key format,
secure production flags, CORS origins, branch and health-check settings.

The output contains **only variable names and sanitized reason codes**,
not keys, values, connection strings, passwords, hostnames or raw provider
responses. Ambiguous service inventories and linked environment groups
cause a closed failure rather than a fabricated green report.

The preflight never creates or modifies resources or env variables,
never deploys, and does not need external datastore network access.
Free-plan datastore lifetime and capacity are flagged as advisories,
not silently treated as durable consumer persistence.

A red inspection against an unconfigured service is a diagnostic, not
a reason to weaken production startup checks. Correct the protected
service environment under an authorized operator's control, then run
inspection before deploying. Never paste credentials into workflow logs.

Render documents the [service environment inventory](https://api-docs.render.com/reference/get-env-vars-for-service),
[Postgres internal connection info](https://api-docs.render.com/reference/retrieve-postgres-connection-info),
and [Key Value internal connection info](https://api-docs.render.com/reference/retrieve-key-value-connection-info).

### 3. Prove the API itself before changing frontend routing

After a reviewed, exact-head API deployment, prove that the existing Render
service starts, listens on its assigned port, and exposes successful
`/health/live` **and** authoritative `/ready` responses with real
configuration and database readiness. Retain tenant isolation, audited auth,
session validation, and the canonical provider registry. Verify Postgres
schema migrations before consumer use.

A healthy HTTP port alone does not establish AI readiness. Also prove a
real configured provider can return model tokens and a verified execution
receipt; the current free CPU hosting plan must not be presumed capable of
serving every local model.

### 4. Repair the effective Vercel backend authority

Vercel must have one deploy-effective `KAREN_BACKEND_URL` set to the
verified healthy **HTTPS origin** of the canonical API. The connected Vercel
project has a sensitive environment-variable record with this name, but
record existence does not prove that the value is populated, valid, or
included in the deployed runtime. Runtime errors showed
`target_status: 'missing'` even after a frontend production build.

Resolve the actual deployed value through Vercel's authorized environment
settings, not through logging it. Redeploy the reviewed frontend only after
the backend is healthy and verify the actual revision. Do not configure
`BACKEND_URL`, `http://api:8000`, `localhost`, or
`host.docker.internal` as a hosted fallback.

The shared Next.js proxy must return an explicit safe 503 when its
canonical target is unavailable. It must never replay mutating POSTs to
alternate hosts or fabricate generated responses.

### 5. Consumer acceptance remains a separate release gate

Run the existing protected browser workflow
`.github/workflows/karen-history-browser-acceptance.yml` using the
`copilotkit-consumer` scenario and the **exact current reviewed main
SHA**. The workflow already checks deployed revision and the canonical
backend proxy before it starts the browser. Its approved URL and test
identity belong in the protected GitHub Actions environment, not in source.

The consumer must prove, end to end, from an authenticated real browser:
one immediate Enter gesture; exactly one executed model POST; a persisted
user prompt followed by a real response; a valid actual-provider/model
receipt; emptied draft state; real incremental rendering; durable history
after reload; no chunk-load or console errors; no cross-tenant retrieval.
Run native Stop and cancellation separately against a disposable owned
conversation, then verify persona, memory recall, tool permission,
presentation and settings paths.

Release evidence must identify both the deployed frontend SHA and the
actual backend/model executor. A READY Vercel build or a green mocked unit
test is not a substitute.

## Existing proof commands

```bash
python -m pytest tests/architecture/test_render_beta_blueprint_contract.py -q
python -m pytest tests/architecture/test_ck28_backend_target_preflight.py -q
python -m pytest tests/architecture/test_production_deployment_contract.py -q

# Requires the approved HTTPS production origin supplied by the operator.
python scripts/ci/verify_backend_target.py --base-url "$KAREN_BASE_URL"
```

The Production Deployment Contract workflow includes the Render Blueprint
contract in its pull-request and main-path triggers.

## Stop conditions

Do **not** mark the beta consumer ready, reconfigure production
`KAREN_BACKEND_URL`, turn on Render auto-deploy, or enable a release
announcement while any of these remain true: Render cannot boot with
required production secrets; its deployed revision is stale; Postgres,
Redis, or provider execution is unavailable; canonical Vercel proxy
configuration is missing; real authenticated model acceptance has not
passed at the deployed exact SHA; or audit/tenant isolation cannot be
verified.

This document is an operator recovery record. It neither provisions
resources nor claims secrets or live infrastructure were repaired.

# KAREN First-Run System

> Status: canonical installation/bootstrap contract
> Owner model: Auth owns initial durable identity; Runtime/Platform own readiness; operators configure optional capabilities through canonical registries/config.

## Objective

A fresh KAREN installation must move from an empty durable database to an authenticated, restart-safe owner account without development bypasses, implicit table creation, fake readiness, or route-level orchestration.

"First run" is not one endpoint. It is a governed lifecycle with explicit authorities and executable proof.

## Authority chain

```text
validated deployment config
        |
        v
canonical migrations
        |
        v
API liveness + auth readiness
        |
        v
GET /api/auth/first-run
        |
        v
POST /api/auth/first-run/setup
        |
        +--> canonical AuthService creates first durable owner + tenant
        +--> RBAC permissions resolved by backend authority
        +--> authenticated HTTP-only session issued
        |
        v
post-setup readiness checks
        |
        +--> provider/model health from canonical model runtime
        +--> memory/persistence health from canonical services
        +--> extensions remain disabled unless governed + authorized
        +--> observability reports backend truth
        |
        v
restart proof + normal login
```

## Ownership

| Concern | Canonical owner | Forbidden shortcuts |
|---|---|---|
| Deployment/config validation | `src/ai_karen_engine/config/` + deployment composition | route-local environment policy, insecure defaults |
| Schema creation/evolution | `supabase/migrations/` | production `AUTO_CREATE_TABLES`, ad-hoc route DDL |
| First-user existence | canonical `AuthService` | UI/localStorage/bootstrap flags |
| First-admin creation | canonical `AuthService.create_first_admin()` | direct route SQL, legacy helper credentials |
| Tenant assignment | canonical auth/user persistence | invented default tenant in UI/route |
| RBAC resolution | backend RBAC authority | frontend role fabrication |
| Session issuance | auth/session authority | browser-auth-only state |
| Provider/model readiness | canonical model runtime/registry | first-run route choosing providers/models |
| Memory readiness | canonical memory/platform health | first-run route mutating memory stores |
| Extension enablement | governed extension runtime + RuntimePolicy | setup route executing/enabling plugins |
| Smoke proof | `scripts/ci/production-first-boot-smoke.sh` | mocked service-only tests |

The public auth route is intentionally thin. It reports whether durable auth bootstrap is needed and delegates creation/authentication to `AuthService`. Provider selection, model downloads, memory orchestration, plugin execution, and runtime policy do not belong in that route.

## Lifecycle states

KAREN treats first-run lifecycle as four observable states:

1. **BOOTSTRAP_BLOCKED**: required production configuration, database, migrations, or auth readiness is unavailable. The system must fail honestly.
2. **OWNER_REQUIRED**: platform is live enough for bootstrap and no durable user exists. `GET /api/auth/first-run` reports `first_run_required=true`.
3. **OWNER_CREATED**: the initial admin/user and tenant are durable, RBAC is resolved, and a session can be issued. A second first-admin creation attempt must not create another bootstrap owner.
4. **OPERATIONAL**: the owner survives process restart and can authenticate normally. Optional provider/model/memory/extension capabilities report their own healthy/degraded/unavailable state rather than changing auth bootstrap truth.

Do not collapse optional AI capability readiness into `first_run_required`. An installation may be securely initialized while a model provider is unavailable; that is an explicit degraded runtime state, not a reason to recreate the administrator.

## Security invariants

Production first run must prove all of the following:

- `ENVIRONMENT=production` and `DEBUG=false`.
- `AUTH_DEV_MODE=false`.
- `AUTH_ALLOW_DEV_LOGIN=false`.
- `KARI_AUTH_BYPASS=false`.
- session validation is enabled.
- production auth auto-table creation is disabled; migrations own schema.
- secrets are supplied by deployment configuration and never returned by first-run status.
- first-admin creation produces durable tenant scope.
- RBAC permissions are resolved by backend authority.
- the session cookie is HTTP-only.
- first-run is one-time and cannot be replayed to create another bootstrap owner.
- restart does not reset first-run state.

## Readiness semantics

First-run endpoints answer only the durable identity-bootstrap question.

After owner creation, operators should verify these independent capability domains:

- API liveness/readiness;
- database and Redis health;
- at least one desired model/provider, if chat inference is expected;
- durable memory dependencies when enabled;
- extension manifest/permission health for enabled extensions;
- metrics/audit export as required by deployment policy.

Each domain must report backend truth. No UI may manufacture a green state.

## Canonical production proof

The first-class proof is container-level, not a mocked unit flow:

```bash
bash -n scripts/ci/production-first-boot-smoke.sh
python scripts/ci/validate_first_run_contract.py
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:first-run .
KAREN_SMOKE_API_IMAGE=ai-karen-api:first-run \
  bash scripts/ci/production-first-boot-smoke.sh
```

The smoke harness must use an isolated network, empty PostgreSQL database, password-protected Redis, canonical migrations, the production API image, production-safe auth flags, first-admin setup, authenticated `/me`, process restart, and normal login after restart.

## Operator runbook

1. Copy the production environment template and replace every secret/example credential.
2. Validate Compose with the production overlay.
3. Apply canonical migrations.
4. Start the production API and dependencies.
5. Confirm `/health/live` and `/api/auth/health`.
6. Confirm `/api/auth/first-run` reports owner setup required only on an empty installation.
7. Create the initial administrator through `/api/auth/first-run/setup`.
8. Confirm first-run becomes false and `/api/auth/me` returns authenticated durable tenant scope.
9. Restart the API and confirm normal login still works.
10. Configure/verify desired provider, model, memory, extensions, and observability through their canonical authorities.

## CI contract

`.github/workflows/production-first-boot-smoke.yml` is the canonical automated first-run gate. It must attest the exact worker SHA, validate this architecture contract, build the production image, and execute the real fresh-install smoke.

Changes to auth bootstrap, production config, Docker/runtime startup, migrations, or the smoke harness must keep this gate green.

# KAREN First-Run System

> **Status:** Canonical installation-bootstrap contract
> **Owner:** AuthService for durable identity/bootstrap state; deployment/migration tooling for infrastructure readiness; API routes remain thin ingress
> **Production proof:** `scripts/ci/production-first-boot-smoke.sh`
> **CI gate:** `.github/workflows/production-first-boot-smoke.yml`

KAREN treats first run as a production lifecycle, not a welcome modal.

A fresh installation is not considered correctly bootstrapped merely because the HTTP server starts. The first-run path must prove that the migration-owned auth schema exists, durable tenant identity can be created, exactly one initial owner can be established, an authenticated session can be issued, bootstrap cannot be re-entered, and the resulting identity survives process restart.

## 1. Authority

First-run responsibility is intentionally split by domain rather than duplicated:

| Responsibility | Canonical owner |
|---|---|
| Database/schema creation | migrations / deployment tooling |
| Auth schema readiness preflight | `AuthService` |
| Determine whether bootstrap is required | `AuthService.is_first_run()` |
| Create installation tenant | `AuthService.create_first_admin()` transaction |
| Create first owner/admin | `AuthService.create_first_admin()` |
| Bootstrap race serialization | PostgreSQL advisory transaction lock in `AuthService` |
| Login/session issuance | canonical `AuthService` authentication/session path |
| HTTP transport | `api_routes/auth/auth.py` |
| Production fresh-install proof | `scripts/ci/production-first-boot-smoke.sh` |
| User-facing first-run flow | UI consumes backend first-run truth only |

The API route must not create tenants or users directly. The UI must not infer first-run state from local storage, browser state, or failed login attempts.

## 2. Canonical state machine

```text
UNREADY
  migration/schema/config preflight fails
  -> explicit unavailable/error

BOOTSTRAP_REQUIRED
  auth schema ready
  + zero durable users
  -> GET /api/auth/first-run => first_run_required=true

BOOTSTRAPPING
  POST /api/auth/first-run/setup
  -> acquire transaction-scoped advisory lock
  -> re-check durable user count
  -> resolve/create installation tenant
  -> create verified admin+user owner
  -> emit audit event
  -> authenticate through normal auth path

CONFIGURED
  one or more durable users exist
  -> GET /api/auth/first-run => first_run_required=false
  -> repeat setup denied
  -> normal login/session path owns access
```

There is no valid state where first-run setup silently creates runtime schema, fabricates a tenant identifier, bypasses password policy, or grants frontend-only admin authority.

## 3. Security invariants

The first-run path is privileged bootstrap code and must fail closed.

Required invariants:

- production/staging auth configuration is validated before bootstrap;
- migration-owned auth tables must already exist;
- the first owner always receives durable tenant scope;
- the initial roles are `admin` and `user` through canonical backend RBAC data;
- bootstrap is serialized across workers with a PostgreSQL transaction advisory lock;
- the user count is re-checked after the lock is acquired;
- a completed installation rejects later first-run setup attempts;
- setup emits an auth audit event;
- tokens are issued only through the normal authentication authority;
- no development auth bypass is part of production first run;
- secrets are not returned in diagnostics or logs beyond normal token responses to the authenticated setup caller.

## 4. Migration ownership

Runtime auth code verifies schema readiness but does not create production tables.

The required auth bootstrap tables currently include:

```text
tenants
auth_users
auth_sessions
auth_refresh_token_history
```

A missing migration is a deployment failure, not an invitation for route-level or service-level `CREATE TABLE` behavior.

## 5. Production proof contract

The production smoke uses the real production API image against isolated infrastructure. It must prove all of the following on an empty database:

1. fresh PostgreSQL/pgvector starts;
2. password-protected Redis starts;
3. canonical SQL migrations apply cleanly;
4. the production API image reaches liveness;
5. auth reaches readiness;
6. first-run status reports setup required;
7. first setup creates an authenticated durable owner;
8. the owner has tenant scope plus `admin` and `user` roles;
9. a second first-run setup attempt is rejected;
10. exactly one durable bootstrap user exists;
11. an active durable tenant exists;
12. `/api/auth/me` resolves the authenticated durable identity;
13. the exact production image restarts;
14. first-run remains completed after restart;
15. the owner can log in again after restart.

This is deliberately stronger than a unit test because installation defects often live at the boundary between migrations, environment configuration, container startup, database state, cookies/tokens, and application initialization.

## 6. Local operator flow

The supported first-run operator sequence is:

```text
copy/validate environment
-> apply/start migration-backed infrastructure
-> start KAREN
-> verify /health/live and /api/auth/health
-> GET /api/auth/first-run
-> POST /api/auth/first-run/setup if required
-> verify authenticated identity
-> configure/verify provider and model availability
-> verify memory/extension/observability services required by the deployment
-> execute the first real chat through the canonical runtime
```

Provider/model setup is intentionally not performed inside `AuthService`. Provider availability belongs to the model-runtime/provider registry. First-run identity bootstrap must not become a second provider orchestrator.

Likewise, memory initialization, extension activation, and observability configuration remain owned by their canonical subsystems. The installation flow may guide operators through those checks, but it must consume backend truth rather than duplicate subsystem logic.

## 7. UI contract

A first-run UI may provide a polished wizard, but it is a renderer/controller over backend truth.

It may:

- call `GET /api/auth/first-run`;
- collect the first owner's name, email, and password;
- call `POST /api/auth/first-run/setup`;
- display explicit backend failures;
- after authentication, guide the owner to provider/model and deployment-health configuration.

It must not:

- invent first-run state;
- save a fake admin locally;
- assign roles client-side;
- create a synthetic tenant;
- mark setup complete if persistence failed;
- silently fall back to development credentials.

## 8. Observability

First-run should be traceable through structured auth/runtime logging without leaking secrets.

At minimum, bootstrap-relevant telemetry should permit operators to distinguish:

- schema/config preflight failure;
- first-run state lookup failure;
- first-admin creation success/failure;
- duplicate/re-entry denial;
- tenant creation/assignment failure;
- session/authentication failure after owner creation.

The existing `auth.first_admin.created` audit event is part of this contract.

## 9. Proof commands

Fast architecture contract:

```bash
pytest tests/architecture/test_first_run_system_contract.py -q
```

Shell validation:

```bash
bash -n scripts/ci/production-first-boot-smoke.sh
```

Real production first-run burn:

```bash
docker build --target app --build-arg PROFILE=runtime -t ai-karen-api:beta .
KAREN_SMOKE_API_IMAGE=ai-karen-api:beta bash scripts/ci/production-first-boot-smoke.sh
```

Normal repository gates still apply:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
npm run lint && npm run typecheck && npm test && npm run build
docker compose config
```

## 10. Remaining maturation work

The durable auth bootstrap is first-class today. The broader installation experience should continue to mature without collapsing subsystem ownership.

Next improvements should be additive orchestration over canonical truth:

- expose a typed post-login installation-readiness view that aggregates provider/model, memory, extension, and observability health without owning those subsystems;
- make the active frontend route fresh installations into the first-run flow automatically from backend status;
- add an end-to-end UI first-run burn against the same production backend contract;
- expose actionable reason codes for deployment/preflight failures;
- move first-run tenant name/slug environment interpretation behind canonical validated configuration during the auth-config cleanup, without creating a second bootstrap config source;
- add an explicit first-real-chat installation proof using an enabled real/local provider in environments where a model runtime is part of the release contract.

These improvements must reuse the current bootstrap authority rather than replacing it with a wizard-specific service or route-level orchestration.

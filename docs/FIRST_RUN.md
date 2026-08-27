# Karen First-Run Setup

Karen's primary installation experience is the web setup flow. `curl` and direct API calls are advanced/headless options, not the normal first-user path.

## Normal first run

1. Start Karen with the deployment profile you intend to use.
2. Open the Web UI, normally `http://localhost:8010`.
3. On a fresh installation, Karen checks backend installation state and opens `/setup`.
4. Karen verifies the API, authentication service, and durable database before allowing account creation.
5. Create the installation owner with your name, email, and a strong unique password.
6. Karen submits the owner bootstrap to the backend.
7. The Web UI re-reads `/api/auth/first-run` and only shows **Karen is ready** after the backend reports `first_run_required: false`.
8. Select **Open Karen** to enter the application.

If the installation is already configured, `/setup` redirects to `/login` instead of exposing first-user creation again.

## Source of truth

The backend is the sole authority for whether first-run setup is required and whether bootstrap has completed. Browser cookies, local storage, route state, and UI flags must never decide whether a new administrator may be created or whether setup is complete.

The setup POST response is not, by itself, completion proof. The client must re-read backend installation state after bootstrap. This protects the UI from reporting success when persistence, a concurrent bootstrap, or another backend-side transition has not actually reached the configured state.

The first user is the installation's initial administrator. RBAC remains the authorization authority after bootstrap. First-run logic must not become a second authorization system.

## UI/UX contract

The setup experience has three user-facing phases:

1. **System check**: show API, authentication, and durable database readiness. Do not silently skip failed dependencies.
2. **Create installation owner**: collect only bootstrap identity and password data. Preserve entered values when a recoverable request fails so the operator can retry.
3. **Karen is ready**: display only after backend-confirmed completion. Do not infer completion from local storage, cookies, navigation state, or a successful HTTP status from the setup mutation alone.

Provider, model, memory, plugin, and extension choices are not owned by first-run UI. Those settings must continue to come from their canonical backend registries and runtime configuration surfaces.

Errors should remain actionable and honest. Validation messages returned by the backend should be surfaced when safe; transport or non-JSON failures should fall back to a generic setup error rather than inventing success or degraded model output.

## Health behavior

The setup UI blocks normal progression when the API, authentication service, or durable database cannot be verified. A failed dependency should be repaired rather than treated as evidence of a fresh installation.

A degraded database state may be displayed as degraded only when the health endpoint explicitly reports that state. Unknown health is not readiness.

Use **Check again** after repairing a dependency. The UI must re-query backend health instead of relying on a cached browser flag.

## Recovery behavior

If owner creation returns an error, remain on the owner step and show the backend error when it is safe to display.

If owner creation succeeds but `/api/auth/first-run` still reports `first_run_required: true`, remain on the owner step and report that backend completion has not been confirmed. Do not show the completion screen. Operators should inspect backend persistence/auth health before retrying.

If setup was completed in another browser or process, revisiting `/setup` should observe backend state and redirect to `/login`.

## Session compatibility

The current browser setup path may adopt authentication data returned by the bootstrap endpoint for compatibility with the existing frontend auth stack. That browser state is not installation truth. The protected backend session, authentication service, RBAC, and persisted installation state remain authoritative.

Any future removal of local token compatibility must be coordinated with the canonical login/session implementation rather than changed only inside first-run setup.

## Headless setup

Automation and headless deployments may use the authentication setup API directly. This is an advanced path and must preserve the same first-run checks, audit behavior, RBAC bootstrap rules, persistence guarantees, and concurrency protections as the browser flow.

A headless caller should verify final installation state after the bootstrap mutation instead of treating the mutation response alone as proof of completion.

## Security invariants

- Never expose first-admin creation after the backend reports the installation configured.
- Never use UI-only checks as authorization.
- Preserve tenant, session, audit, and RBAC enforcement during bootstrap.
- Never log passwords, tokens, or other secrets in setup telemetry.
- Do not let provider fallback, degraded runtime behavior, or frontend defaults alter installation-state truth.
- Setup failures must fail closed. An unavailable status endpoint is not equivalent to a fresh installation.

## Authentication roadmap

Karen should add WebAuthn/passkey support as a real authentication capability, not as a decorative UI control. Implementation requires credential persistence, registration and authentication ceremonies, recovery policy, re-authentication for sensitive actions, audit events, and tenant-aware credential ownership.

Current standards/reference guidance:

- W3C Web Authentication Level 3: https://www.w3.org/TR/webauthn-3/
- OWASP Authentication Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- OWASP Multifactor Authentication Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html

## Verification

Frontend:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm test
npm run build
```

First-run E2E:

```bash
cd src/ui_launchers/Karen-AI-Theme
npx playwright test e2e/test_first_run_setup.spec.ts
```

The first-run E2E contract must prove both sides of completion behavior:

- a fresh installation progresses only after a second backend status check reports configured;
- a successful owner-creation response does not show **Karen is ready** while the backend still reports first-run required.

Backend and repository-wide checks:

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q
docker compose config
```

# Karen First-Run Setup

Karen's primary installation experience is the web setup flow. `curl` and direct API calls are advanced/headless options, not the normal first-user path.

## Normal first run

1. Start Karen with the deployment profile you intend to use.
2. Open the Web UI, normally `http://localhost:8010`.
3. On a fresh installation, Karen checks backend installation state and opens `/setup`.
4. Karen verifies the API, authentication service, and durable database before allowing account creation.
5. Create the installation owner with your name, email, and a strong unique password.
6. Karen creates the first administrator, establishes the browser session, and confirms setup completion.
7. Select **Open Karen** to enter the application.

If the installation is already configured, `/setup` redirects to `/login` instead of exposing first-user creation again.

## Setup ownership

The backend is the source of truth for whether first-run setup is required. Browser cookies, local storage, route state, and UI flags must never decide whether a new administrator may be created.

The first user is the installation's initial administrator. RBAC remains the authorization authority after bootstrap.

## Health behavior

The setup UI blocks normal progression when the API, authentication service, or durable database cannot be verified. A failed dependency should be repaired rather than treated as evidence of a fresh installation.

## Headless setup

Automation and headless deployments may use the authentication setup API directly. This is an advanced path and must preserve the same first-run checks, audit behavior, and concurrency guarantees as the browser flow.

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
cd src/ui_launchers/Karen-AI-Theme/e2e
npx playwright test test_first_run_setup.spec.ts
```

Backend and repository-wide checks:

```bash
python -m compileall src
ruff check src tests
mypy src
pytest tests/ -q
docker compose config
```

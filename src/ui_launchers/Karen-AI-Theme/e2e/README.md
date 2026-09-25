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

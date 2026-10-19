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

The private GitHub artifact is retained for seven days and may contain chat
text, screenshots, browser recordings and traces. Authorized reviewers must
inspect and sanitize it before any public publication. The Playwright assertion
receipt explicitly does not prove NeuroVault long-term memory projection.
Do not mark release acceptance complete merely because the workflow dispatch
was accepted, skipped, or queued.

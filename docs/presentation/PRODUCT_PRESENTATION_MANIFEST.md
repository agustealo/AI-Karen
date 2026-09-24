# KAREN Product Presentation Manifest

**Scope:** product identity, repository presentation, screenshot provenance, and public-facing feature claims.

This manifest does **not** supersede `PROJECT_DEV_MANIFEST.md`. The root developer manifest remains the architecture and delivery authority. This file owns presentation truth only.

## Presentation source of truth

| Responsibility | Canonical owner |
|---|---|
| Architecture and runtime claims | `PROJECT_DEV_MANIFEST.md` plus canonical architecture docs |
| Brand assets | `src/ui_launchers/Karen-AI-Theme/public/brand/` |
| Web app metadata/PWA identity | `src/ui_launchers/Karen-AI-Theme/src/app/layout.tsx` and `src/app/manifest.ts` |
| Screenshot capture | `src/ui_launchers/Karen-AI-Theme/e2e/showcase/` |
| Screenshot provenance verification | `scripts/ci/verify_presentation_assets.py` |
| Presentation integrity CI | `.github/workflows/presentation-contract.yml` |
| Approved remote capture | `.github/workflows/presentation-capture.yml` |
| Curated screenshots | `docs/assets/screenshots/` |
| Brand rules | `docs/presentation/BRAND_SYSTEM.md` |
| Repository presentation | root `README.md` |

## Brand contract

**Name:** KAREN  
**Positioning:** Local-first cognitive runtime  
**Primary line:** Local by default. Governed by design.

The brand deliberately converts the cultural "Karen" escalation trope into a systems-operator idea. KAREN is the layer that knows the owner, applies the policy, routes the work, and preserves execution truth. The reference must remain subtle and abstract so the identity survives the meme cycle.

## Claims allowed in public presentation

The following claims map to live repository surfaces or canonical architecture and may be used without inventing product capability:

- governed chat through the canonical runtime;
- local-first provider/model orchestration;
- prompt-first execution contracts;
- durable layered memory and governed recall/persistence;
- agents and workflow surfaces;
- governed plugin/extension path;
- Comms Center product surface;
- application settings backed by backend truth;
- RBAC, tenant isolation, audit, and action permission boundaries;
- structured degradation/fallback provenance and observability;
- production first-run contract and durable owner bootstrap.

Do not market planned work as shipped capability. Do not infer a provider, model, extension, or health state in presentation copy when the backend does not report it.

## Screenshot contract

A screenshot qualifies for public product presentation only when all of the following are true:

1. It is captured by Playwright from the real application UI.
2. The target is a real running KAREN stack, not a static mock server.
3. Authentication uses a dedicated sanitized demo account.
4. The capture is explicitly opted in with `KAREN_SHOWCASE_ALLOW_CAPTURE=true`.
5. No personal conversation, secret, token, provider key, private email, or production tenant data is visible.
6. The screen represents a capability that exists at the captured commit.
7. The capture rail emits `capture-manifest.json` with exact git SHA, browser, viewport, account class, and no-synthetic-state policy.
8. `python scripts/ci/verify_presentation_assets.py --require-assets` passes.
9. The image is reviewed at native resolution before it is promoted into README hero/gallery placement.

The capture rail writes these canonical files:

```text
docs/assets/screenshots/
├── 01-chat-runtime.png
├── 02-agents-overview.png
├── 03-plugin-ecosystem.png
├── 04-comms-center.png
├── 05-settings-and-models.png
└── capture-manifest.json
```

No generated or hand-composited substitute may use these filenames.

## Capture environments

Two capture paths are supported, and both use the same Playwright owner:

- **Local approved demo installation:** invoke `npm run showcase:capture` with an explicitly sanitized account.
- **Approved remote demo deployment:** invoke `.github/workflows/presentation-capture.yml`, which reads the HTTPS origin and sanitized credentials from repository secrets.

Presentation code must not change the production first-boot smoke harness merely to make media capture easier. Authentication/bootstrap remains owned by the canonical auth/first-run system.

## Current media status

- Canonical mark: ready
- Canonical wordmark: ready
- Repository/social banner: ready
- Web metadata and install manifest: wired
- Real browser screenshot provenance: preserved in `e2e-current-browser-proof.png`
- Curated five-screen gallery: must be regenerated from an approved sanitized live stack before this slice is considered presentation-complete

The raw E2E proof image is intentionally not treated as a marketing hero. It demonstrates provenance only.

## Release gate

Structural presentation contract:

```bash
python scripts/ci/verify_presentation_assets.py
```

Real gallery capture and proof:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run typecheck
npm run build
KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_EMAIL='<sanitized-demo-email>' \
KAREN_SHOWCASE_PASSWORD='<sanitized-demo-password>' \
KAREN_SHOWCASE_BASE_URL='http://localhost:8010' \
npm run showcase:capture
cd ../../..
python scripts/ci/verify_presentation_assets.py --require-assets
```

Then manually review all five PNGs for visual polish, privacy, stale errors, debug overlays, broken loading states, and accurate feature representation.

The screenshot gate is intentionally fail-closed. Missing approval or credentials is an error, not permission to create fake media.

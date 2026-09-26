# KAREN Product Presentation Manifest

**Scope:** product identity, repository presentation, screenshot provenance, and public-facing feature claims.

This manifest does **not** supersede `PROJECT_DEV_MANIFEST.md`. The root developer manifest remains the architecture and delivery authority. This file owns presentation truth only.

## Presentation source of truth

| Responsibility | Canonical owner |
|---|---|
| Architecture and runtime claims | `PROJECT_DEV_MANIFEST.md` plus canonical architecture docs |
| Brand assets | `src/ui_launchers/Karen-AI-Theme/public/brand/` |
| Web app metadata/PWA identity | `src/ui_launchers/Karen-AI-Theme/src/app/layout.tsx` and `src/app/manifest.ts` |
| Authenticated shell identity | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` using canonical `/brand/` assets |
| Trusted screenshot capture harness | `main`: `src/ui_launchers/Karen-AI-Theme/e2e/showcase/` |
| Reusable screenshot provenance | `main`: `scripts/ci/presentation_gallery_contract.py` |
| KAREN presentation integration | `scripts/ci/verify_presentation_assets.py` |
| Presentation integrity CI | `.github/workflows/presentation-contract.yml` |
| Approved remote capture/credential boundary | `main`: `.github/workflows/presentation-capture.yml` |
| Capture trust-boundary proof | `main`: `.github/workflows/presentation-capture-trust-boundary.yml` and `tests/architecture/test_presentation_capture_trust_boundary.py` |
| Curated screenshots | `docs/assets/screenshots/` |
| Brand rules | `docs/presentation/BRAND_SYSTEM.md` |
| Repository presentation | root `README.md` |

## Brand contract

**Name:** KAREN  
**Positioning:** Local-first cognitive runtime  
**Primary line:** Local by default. Governed by design.

The brand deliberately converts the cultural "Karen" escalation trope into a systems-operator idea. KAREN is the layer that knows the owner, applies the policy, routes the work, and preserves execution truth. The reference must remain subtle and abstract so the identity survives the meme cycle.

The public product name is **KAREN**. `Karen AI` is a retired split-brand label and must not appear on curated product surfaces. Compatibility identifiers may remain internally where changing them would alter contracts, but they are not presentation copy.

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
6. The screen represents a capability that exists in the repository line identified by the operator-attested target revision.
7. The authenticated shell visibly uses the canonical KAREN mark and name before capture begins.
8. The capture rail emits `capture-manifest.json` with capture-harness SHA, target revision, browser, viewport, account class, and no-synthetic-state policy.
9. Remote capture executes from trusted default-branch workflow code and the target revision contains the exact trusted `main` capture baseline for that run.
10. The destination is an existing non-default branch; the secret-bearing job does not execute destination-branch code.
11. Every curated surface is in a presentation-ready state, not merely mounted.
12. Chat contains a real non-sensitive conversation from the sanitized demo account.
13. Agents Overview has entered its explicit verified `ready` state from validated backend statistics; unavailable/defaulted metrics are prohibited.
14. Plugin Overview has finished resolving registry/backend lifecycle state.
15. Comms Center is showing live observability rather than authentication, authorization, or fallback warnings.
16. No curated surface visibly renders the retired `Karen AI` split brand.
17. `python scripts/ci/verify_presentation_assets.py --require-assets` passes.
18. The image is reviewed at native resolution before it is promoted into README hero/gallery placement.

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

### Revision provenance

The capture harness checkout and the running application are separate facts. `capture-manifest.json` therefore records:

- `capture_harness_git_sha`: the exact trusted repository checkout that ran Playwright;
- `target_revision`: the full application revision the capture operator attests is deployed at the target;
- `target_revision_attestation: operator-supplied`.

The remote workflow requires `target_revision` to be a known commit descended from the exact trusted `main` harness SHA. The presentation integration gate additionally requires both recorded revisions to belong to the current presentation branch line before the gallery may be promoted.

KAREN does not currently expose a canonical runtime endpoint that self-attests deployment revision. Public documentation must not describe `target_revision` as self-verified until such a runtime/deployment contract exists.

## Capture trust boundary

Remote media capture intentionally separates secret access from repository write authority:

```text
main-owned workflow + harness
        │
        │ read-only repo + sanitized demo credentials
        ▼
real live KAREN capture
        │
        ▼
trusted gallery verifier
        │
        ▼
immutable evidence artifact
        │
        │ no capture credentials
        ▼
write-scoped destination job
        │
        ├─ stages six fixed gallery files only
        ├─ rejects symlinked destination paths
        ├─ runs verifier shipped in trusted artifact
        └─ commits gallery to non-default branch
```

The write-scoped job must not execute Python or Node code from the destination branch. Presentation convenience does not outrank credential isolation.

## Capture environments

Two capture paths are supported, and both use the same Playwright owner:

- **Local approved demo installation:** invoke `npm run showcase:capture` with an explicitly sanitized account and `KAREN_SHOWCASE_TARGET_REVISION=<full deployed SHA>`.
- **Approved remote demo deployment:** use the trusted default-branch **KAREN Presentation Capture** workflow. The preferred repository-owner ingress from the target pull request is `/capture-presentation <full-40-character-current-pr-head-sha>`. The workflow requires repository-owner identity plus `OWNER` author association and binds the requested SHA to the pull request's current head before capture secrets are exposed. Manual `workflow_dispatch` from workflow ref `main` remains supported with `target_revision=<full deployed SHA>`, `destination_branch=docs/premium-brand-showcase`, and `commit_assets=true`. The HTTPS origin and sanitized credentials come only from repository Actions secrets.

Do not execute credential-bearing capture code from the presentation branch. The workflow intentionally keeps secret-bearing execution default-branch-owned.

Presentation code must not change the production first-boot smoke harness merely to make media capture easier. Authentication/bootstrap remains owned by the canonical auth/first-run system.

## Current media status

- Canonical mark: ready
- Canonical wordmark: ready
- Repository/social banner: ready
- Web metadata and install manifest: wired
- Authenticated application shell: wired to canonical KAREN mark/name
- Agents Overview: fail-closed on unavailable/malformed backend statistics
- Plugin Overview presentation copy: converged to KAREN
- Remote capture trust boundary: production-owned and CI-proven on `main`
- Generic Playwright reports/results: retired as presentation evidence; generated browser-test output is not a release-proof source
- Curated five-screen gallery: absent and must be captured from an approved sanitized live stack before this slice is presentation-complete

## Release gate

Structural presentation contract:

```bash
python scripts/ci/verify_presentation_assets.py
```

Real gallery capture and proof for a local approved deployment:

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run typecheck
npm run build
KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_EMAIL='<sanitized-demo-email>' \
KAREN_SHOWCASE_PASSWORD='<sanitized-demo-password>' \
KAREN_SHOWCASE_TARGET_REVISION='<full-40-character-deployed-sha>' \
KAREN_SHOWCASE_BASE_URL='http://localhost:8010' \
npm run showcase:capture
cd ../../..
python scripts/ci/verify_presentation_assets.py --require-assets
```

Then manually review all five PNGs for visual polish, privacy, stale errors, debug overlays, broken loading states, canonical naming, and accurate feature representation.

The screenshot gate is intentionally fail-closed. Missing approval, target revision, credentials, real chat evidence, healthy feature state, or canonical branding is an error, not permission to create fake media.

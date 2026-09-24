# KAREN Screenshot Provenance

This directory contains public-facing product captures. Images here are evidence, not decoration.

## Hard rule

Only real browser captures of the real KAREN UI may be committed as product screenshots. Do not place generated dashboards, design mockups, edited feature composites, or static test substitutes here and present them as application truth.

The curated gallery is valid only when its five PNG files are accompanied by `capture-manifest.json` from the canonical Playwright capture rail. A screenshot without provenance is not product proof.

## Canonical ownership

The executable remote-capture authority lives on the default branch:

- `.github/workflows/presentation-capture.yml` owns dispatch and credential isolation;
- `src/ui_launchers/Karen-AI-Theme/e2e/showcase/` owns the real-browser capture harness;
- `scripts/ci/presentation_gallery_contract.py` owns reusable gallery provenance validation;
- `scripts/ci/verify_presentation_assets.py` adds KAREN brand/presentation integration and current-branch attribution;
- this directory owns only the resulting curated evidence.

A presentation branch must not replace the main-owned capture authority merely to obtain screenshots.

## Canonical capture

### Local approved demo installation

From the active UI package:

```bash
cd src/ui_launchers/Karen-AI-Theme

KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_EMAIL='<sanitized-demo-email>' \
KAREN_SHOWCASE_PASSWORD='<sanitized-demo-password>' \
KAREN_SHOWCASE_TARGET_REVISION='<full-40-character-deployed-sha>' \
KAREN_SHOWCASE_BASE_URL='http://localhost:8010' \
npm run showcase:capture
```

`KAREN_SHOWCASE_BASE_URL` may target another approved test installation. The target must be a real running KAREN deployment with its real backend dependencies available.

`KAREN_SHOWCASE_TARGET_REVISION` is an operator attestation of the revision actually deployed at that target. The capture harness records its own checkout SHA separately. Until KAREN exposes a canonical deployment-revision attestation endpoint, the two values must never be collapsed into a single "captured SHA" claim.

The rail refuses to run unless the account is explicitly declared `sanitized-demo`. This is deliberate. Do not capture a personal or production account for convenience.

### GitHub capture from the approved demo deployment

The registered workflow is `.github/workflows/presentation-capture.yml`. The **workflow ref must be `main`** so every secret-bearing command executes code owned by the trusted default branch.

Use these inputs:

```text
target_revision=<full 40-character SHA actually deployed>
destination_branch=docs/premium-brand-showcase
commit_assets=true
```

Repository secrets must provide:

```text
KAREN_PRESENTATION_BASE_URL
KAREN_PRESENTATION_EMAIL
KAREN_PRESENTATION_PASSWORD
```

The target revision must be a known commit descended from the exact trusted `main` capture baseline used by that workflow run. The destination must be an existing non-default branch.

The workflow requires HTTPS, authenticates through the real UI, records the exact trusted capture-harness checkout, records the separately attested target revision, validates the gallery, and uploads immutable evidence. The capture job is read-only and has the demo credentials. The later repository-write job receives **no capture URL, email, or password**, stages only the six canonical gallery files, rejects symlinked destination paths, and re-validates the evidence with the trusted verifier shipped inside the capture artifact. It does not execute destination-branch Python or Node code under write permission.

Do not dispatch the credential-bearing workflow from a feature/presentation branch. That path is intentionally rejected.

## Expected curated set

```text
01-chat-runtime.png
02-agents-overview.png
03-plugin-ecosystem.png
04-comms-center.png
05-settings-and-models.png
capture-manifest.json
```

`capture-manifest.json` records:

- capture-harness git SHA;
- operator-attested target application revision;
- browser version;
- viewport;
- sanitized-account declaration;
- explicit policy that mocked responses, generated UI, fixture-only state, and production/personal data were not used.

The operator-attested target revision is honest provenance, not self-attestation by the running app. Do not describe it as cryptographically verified deployment identity unless a future canonical runtime/deployment contract actually provides that proof.

Before committing a capture, inspect every PNG at full resolution and verify:

- no PII, private conversations, private tenant data, tokens, credentials, or provider keys;
- no console/debug overlays, stack traces, failed health state, or loading skeleton frozen mid-transition;
- no placeholder or fabricated business data represented as production truth;
- navigation and labels are consistent with the attested target revision;
- typography, spacing, clipping, responsive layout, and contrast are presentation quality;
- the screenshot still demonstrates a capability that is active in the repository.

## Automated integrity gates

Reusable gallery provenance is checked with:

```bash
python scripts/ci/presentation_gallery_contract.py
```

Presentation integration is checked with:

```bash
python scripts/ci/verify_presentation_assets.py
```

Once the curated gallery exists, release/presentation proof must use the stricter form:

```bash
python scripts/ci/verify_presentation_assets.py --require-assets
```

The shared gallery contract rejects partial galleries, invalid PNGs, invalid or unknown revisions, bad provenance, unexpected viewport dimensions, and non-sanitized account provenance. The presentation verifier delegates those checks to that canonical owner, then enforces KAREN brand/capture integration and requires both harness and target revisions to belong to the current presentation line.

## Existing E2E proof

`e2e-current-browser-proof.png` is copied byte-for-byte from the repository's committed Playwright report blob. It is retained only as proof that a real browser image already exists in project history. It is uncurated and must not automatically become the README hero or product gallery.

## Curation policy

The README may promote only reviewed files from the expected curated set. If a screen changes materially, regenerate the relevant image from the current product state rather than editing the old PNG.

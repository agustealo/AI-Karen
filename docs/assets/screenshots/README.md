# KAREN Screenshot Provenance

This directory contains public-facing product captures. Images here are evidence, not decoration.

## Hard rule

Only real browser captures of the real KAREN UI may be committed as product screenshots. Do not place generated dashboards, design mockups, edited feature composites, or static test substitutes here and present them as application truth.

The curated gallery is valid only when its five PNG files are accompanied by `capture-manifest.json` from the canonical Playwright capture rail. A screenshot without provenance is not product proof.

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

The repository also provides `.github/workflows/presentation-capture.yml`. It reads the target and credentials only from these repository secrets:

```text
KAREN_PRESENTATION_BASE_URL
KAREN_PRESENTATION_EMAIL
KAREN_PRESENTATION_PASSWORD
```

The workflow also requires a `target_revision` input containing the full deployed 40-character SHA. It verifies that the attested revision is a known commit and belongs to the current repository line before capture proceeds.

The workflow requires an HTTPS target, authenticates through the real UI, records the exact capture-harness checkout, records the separately attested target revision, verifies the resulting gallery, and can optionally commit the validated media back to the selected non-default branch. It does not modify, wrap, or weaken the production first-boot smoke path.

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

## Automated integrity gate

Structural presentation integrity is checked with:

```bash
python scripts/ci/verify_presentation_assets.py
```

Once the curated gallery exists, release/presentation proof must use the stricter form:

```bash
python scripts/ci/verify_presentation_assets.py --require-assets
```

The verifier rejects partial galleries, invalid PNGs, unknown/non-ancestor harness or target revisions, missing provenance, unexpected viewport dimensions, synthetic capture primitives, and non-sanitized account provenance.

## Existing E2E proof

`e2e-current-browser-proof.png` is copied byte-for-byte from the repository's committed Playwright report blob. It is retained only as proof that a real browser image already exists in project history. It is uncurated and must not automatically become the README hero or product gallery.

## Curation policy

The README may promote only reviewed files from the expected curated set. If a screen changes materially, regenerate the relevant image from the current product state rather than editing the old PNG.

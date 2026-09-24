# KAREN Screenshot Provenance

This directory contains public-facing product captures. Images here are evidence, not decoration.

## Hard rule

Only real browser captures of the real KAREN UI may be committed as product screenshots. Do not place generated dashboards, design mockups, edited feature composites, or static test substitutes here and present them as application truth.

## Canonical capture

From the active UI package:

```bash
cd src/ui_launchers/Karen-AI-Theme

KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_EMAIL='<sanitized-demo-email>' \
KAREN_SHOWCASE_PASSWORD='<sanitized-demo-password>' \
KAREN_SHOWCASE_BASE_URL='http://localhost:8010' \
npm run showcase:capture
```

`KAREN_SHOWCASE_BASE_URL` may target another approved test installation. The target must be a real running KAREN deployment with its real backend dependencies available.

The rail refuses to run unless the account is explicitly declared `sanitized-demo`. This is deliberate. Do not capture a personal or production account for convenience.

## Expected curated set

```text
01-chat-runtime.png
02-agents-overview.png
03-plugin-ecosystem.png
04-comms-center.png
05-settings-and-models.png
```

Before committing a capture, inspect it at full resolution and verify:

- no PII, private conversations, private tenant data, tokens, credentials, or provider keys;
- no console/debug overlays, stack traces, failed health state, or loading skeleton frozen mid-transition;
- no placeholder or fabricated business data represented as production truth;
- navigation and labels match the captured commit;
- typography, spacing, clipping, responsive layout, and contrast are presentation quality;
- the screenshot still demonstrates a capability that is active in the repository.

## Existing E2E proof

`e2e-current-browser-proof.png` is copied byte-for-byte from the repository's committed Playwright report blob. It is retained only as proof that a real browser image already exists in project history. It is uncurated and must not automatically become the README hero or product gallery.

## Curation policy

The README may promote only reviewed files from the expected curated set. If a screen changes materially, regenerate the relevant image from the current exact head rather than editing the old PNG.

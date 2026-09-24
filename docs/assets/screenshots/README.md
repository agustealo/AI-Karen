# KAREN Product Screenshots

This directory is reserved for **real screenshots captured from a running KAREN installation**.

Do not commit generated UI mockups, Figma recreations, fixture-only product states, edited values, or screenshots without provenance.

The canonical capture command is:

```bash
cd src/ui_launchers/Karen-AI-Theme
KAREN_CAPTURE_EMAIL='owner@example.com' \
KAREN_CAPTURE_PASSWORD='...' \
KAREN_BASE_URL='http://localhost:8010' \
npm run capture:presentation
```

A successful run writes:

- `01-login.png`
- `02-chat-runtime.png`
- `03-comms-center.png`
- `04-agents-overview.png`
- `05-plugin-overview.png`
- `06-settings.png`
- `capture-manifest.json`

The manifest records exact Git SHA, capture time, origin, browser, viewport, identity mode, and the no-mock product-photography policy.

Screenshots should be replaced when the corresponding product surface materially changes. Never hand-edit UI content to make the product look more complete than the captured build actually was.

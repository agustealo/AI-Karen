# KAREN Brand & Presentation System

## Purpose

KAREN should look like the product it is becoming: a durable cognitive runtime, not a novelty chatbot and not a meme reskin.

The name deliberately flips the internet's "Karen" archetype. The familiar cultural reference gives the name instant recall, but the visual system does not imitate the haircut, caricature a person, or depend on a joke that will age. The inversion is conceptual:

- stereotype: loud, intrusive, demanding;
- KAREN: composed, private, governed, evidence-aware;
- stereotype: asks for authority;
- KAREN: makes authority explicit and auditable;
- stereotype: chaos in public;
- KAREN: control, continuity, and local-first intelligence.

Humor can live in campaign copy. The core identity stays premium and timeless.

## Identity

**Primary name:** KAREN  
**Product description:** Local-first cognitive runtime  
**Primary line:** Memory. Models. Tools. Reasoning. Governance.  
**Supporting line:** One runtime. One identity boundary. Built to remember what matters and prove what happened.

Avoid calling KAREN a generic assistant in primary brand surfaces. "Assistant" is a capability, not the product category.

## Mark

The mark is a geometric `K` built from three ideas:

1. a stable vertical spine for runtime authority;
2. two branching facets for cognition and action;
3. a small signal accent for awareness/observability.

It hints at the famous KAREN silhouette only at the level of asymmetry and recognizable attitude. It must never become a literal haircut icon, face, photorealistic person, or stock avatar.

Canonical source assets:

- `docs/assets/brand/karen-mark.svg`
- `docs/assets/brand/karen-banner.svg`
- `src/ui_launchers/Karen-AI-Theme/public/brand/karen-mark.svg`
- `src/ui_launchers/Karen-AI-Theme/public/brand/karen-banner.svg`

## Visual language

KAREN uses near-black/navy surfaces, restrained cool signal gradients, generous negative space, and precise typography. The interface may support light mode, but flagship product photography should use the mode that best represents the current production UI rather than forcing a marketing-only theme.

The signal gradient is an accent, not wallpaper. Keep it on identity marks, focus states, data highlights, and small moments of energy. Most of the product should remain calm.

### Core palette

| Token | Value | Use |
| --- | --- | --- |
| Obsidian | `#090D16` | flagship dark background |
| Graphite | `#111827` | elevated surfaces |
| Frost | `#F7FAFF` | primary text on dark |
| Mist | `#C9D3E4` | secondary text |
| Signal Mint | `#84E8D5` | signal gradient start |
| Signal Blue | `#64BAFF` | signal gradient middle |
| Signal Violet | `#9B8CFF` | signal gradient end |

The application UI remains driven by canonical theme tokens. Brand hex values must not become a second UI-theme authority.

## Typography

Use the application's system-first sans stack unless a licensed product font is deliberately adopted. Do not make the logo depend on a downloadable font file. Wordmarks should remain reproducible with system typography and the geometric symbol.

## Product photography rule

**Only real application state may appear in README, release, website, or store screenshots.**

Forbidden:

- Figma recreations presented as product UI;
- generated UI images;
- mocked API responses;
- fixture-only providers presented as live providers;
- fake conversations;
- fake health states;
- edited values that the application did not render;
- screenshots from an unidentifiable code revision.

Allowed post-processing is limited to lossless crop, privacy redaction of real user data, and composition onto a neutral presentation canvas. Do not alter product content or imply unavailable capability.

## Canonical capture set

The presentation capture rail writes the following evidence from a real running installation:

1. `01-login.png` - secure identity entry and brand posture;
2. `02-chat-runtime.png` - primary governed chat/runtime workspace;
3. `03-comms-center.png` - communications surface;
4. `04-agents-overview.png` - governed automation / agent topology;
5. `05-plugin-overview.png` - extension ecosystem surface;
6. `06-settings.png` - runtime/application configuration surface.

Not every public document needs all six images. The README should lead with the strongest current 2-4 screenshots and link to the gallery for the rest.

## Screenshot provenance

Every committed screenshot set must include `docs/assets/screenshots/capture-manifest.json` with:

- exact Git SHA;
- capture timestamp;
- base URL origin, without credentials or query secrets;
- viewport;
- browser engine;
- authenticated capture mode;
- files produced.

A screenshot is stale when the product UI materially changed after its recorded Git SHA. Stale screenshots should be replaced, not cosmetically patched.

## Capture command

Run against a healthy local or staged installation with a real account:

```bash
cd src/ui_launchers/Karen-AI-Theme
KAREN_CAPTURE_EMAIL='owner@example.com' \
KAREN_CAPTURE_PASSWORD='...' \
KAREN_BASE_URL='http://localhost:8010' \
npm run capture:presentation
```

For username login, use `KAREN_CAPTURE_USERNAME` instead of `KAREN_CAPTURE_EMAIL`.

The capture test fails when credentials are absent, authentication does not succeed, backend health is not ready, or required product views cannot be reached. This is intentional. Marketing evidence must fail closed.

## README / docs presentation order

The premium repository story should stay concise:

1. brand banner;
2. one-sentence product category and value;
3. real screenshots;
4. key capabilities;
5. architecture authority model;
6. install / first-run path;
7. proof, security, and observability;
8. developer deep links.

Do not lead the public README with implementation debt, long architecture doctrine, or internal cleanup history. Keep those truths in the developer manifest and architecture documentation.

## Release rule

Do not merge a presentation refresh that claims real screenshots until the capture files exist and their exact-head provenance is recorded. Brand assets may land independently, but screenshot claims remain gated on product evidence.

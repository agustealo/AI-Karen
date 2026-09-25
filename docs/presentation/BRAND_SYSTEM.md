# KAREN Brand System

## Intent

KAREN's visual identity should feel like infrastructure with taste: calm, precise, capable, and durable. It must not look like a novelty AI wrapper or a literal meme adaptation.

The cultural reference behind the name is deliberately inverted. The familiar "Karen" trope is about demanding escalation and asking for the manager. KAREN turns that energy into the product role: the composed operator that knows who owns a responsibility, routes work to the right authority, keeps policy boundaries intact, and can explain what actually happened.

That idea belongs in the story, not as a cartoon. No literal meme face, celebrity likeness, dated haircut illustration, joke typography, or complaint gag belongs in the canonical identity.

## Canonical identity

The mark is an abstract **K** built from three ideas:

1. a stable vertical spine for the runtime authority;
2. two routed branches for orchestration and extension;
3. a central node for governed decision handoff.

The shallow arc above the mark is the only visual wink to the cultural reference. It is intentionally abstract enough to read as topology, a horizon, or a signal arc rather than a hairstyle.

Canonical assets live in exactly one product-owned location:

```text
src/ui_launchers/Karen-AI-Theme/public/brand/
├── karen-mark.svg
├── karen-wordmark.svg
└── karen-banner.svg
```

Documentation should reference these files instead of creating duplicate logos.

## Palette

The identity uses the application's existing tokens rather than establishing a second visual system.

| Role | Value | Use |
|---|---:|---|
| Charcoal | `#18181B` | Primary foundation and dark surfaces |
| Paper white | `#F8F7FB` | Primary high-contrast type and spine |
| KAREN lavender | `#CF75FF` | Primary brand signal |
| Soft lavender | `#E7D8FF` | Highlights and quiet emphasis |
| Deep violet | `#9B5CFF` | Gradient depth and routed branches |
| Muted text | `#A9A5B2` | Secondary information |

Do not introduce a competing primary color without changing the application theme source of truth first.

## Typography

The active web application uses Inter. Brand artwork therefore uses Inter as its preferred face with system sans-serif fallbacks. The wordmark is uppercase with restrained tracking. Product copy remains sentence case.

## Voice

Preferred language is concise and operational. KAREN should sound confident because the system exposes evidence, not because the copy shouts.

Canonical positioning line:

> **Local by default. Governed by design.**

Supporting description:

> A local-first, prompt-first AI runtime for governed chat execution, durable memory, provider orchestration, agents, extensions, and observable automation.

## Logo usage

Use `karen-mark.svg` for compact product chrome, icons, avatars, and square placements. Use `karen-wordmark.svg` when the name must be explicit. Use `karen-banner.svg` for repository, launch, documentation, and social-header presentation.

Keep clear space around the mark equal to at least one quarter of the mark width. Do not distort, rotate, add novelty effects, redraw the K, recolor it with unrelated gradients, or place it over visually noisy imagery.

## Screenshot language

Product screenshots are part of the brand. They must be produced by the real UI against a real running KAREN stack. Synthetic dashboard images, Figma substitutes presented as product truth, generated screenshots, and mocked feature cards are prohibited.

Approved showcase surfaces are:

- Chat runtime
- Agents Overview
- Plugin Overview
- Comms Center
- Application Settings and model controls

Use a dedicated sanitized demo installation. Never capture personal conversations, production tenant data, secrets, tokens, provider keys, or private account details.

The canonical capture procedure is documented in `docs/assets/screenshots/README.md`.

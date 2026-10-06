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

## Palette and surface system

The application theme is the only color authority. Canonical product colors are semantic CSS tokens in:

`src/ui_launchers/Karen-AI-Theme/src/app/globals.css`

The system defines coordinated light and dark values for background, foreground, card, muted, border, input, primary, accent, destructive, success, warning, information, and sidebar roles. The product also defines `surface-0` through `surface-3` for depth. Screens, plugins, settings, automation views, auth, setup, and chat must consume those roles rather than copying hex values into feature code.

The current brand signal is a restrained violet primary paired with a cyan/teal information accent. Status colors are reserved for semantic state. Decorative gradients may combine existing tokens, but must not become an independent palette.

Do not introduce a competing primary color or page-local color system. Change the global token source of truth first, then let shared primitives propagate the update.

## Typography

Typography is local/system-first and network-independent. The canonical stacks are declared in `globals.css`:

- **Sans / product copy:** Avenir Next → Segoe UI Variable → Segoe UI → Inter → system UI fallbacks.
- **Mono / instrumentation:** SFMono-Regular → Cascadia Code → Roboto Mono → Consolas → Liberation Mono → monospace.

Product copy remains sentence case. Compact runtime labels, receipts, identifiers, and execution instrumentation may use the mono stack with restrained uppercase tracking. Display headings use tighter tracking and stronger weight, not a separate display font.

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

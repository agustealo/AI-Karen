# Kari OS chat design contract (KUI-001)

Status: **staged, opt-in**. This contract does not represent completed chat UI integration.
Source: approved Kari OS chat workspace HTML and KARI-OS-CHAT-DEV-SHEET v1.1 (2026-11-18), preserved in the project's persistent design Library.

## Ownership and non-negotiable behavior

- Existing frontend owner: `src/ui_launchers/Karen-AI-Theme` (Next.js / Tailwind / Radix).
- Existing global semantics: `src/app/globals.css`; don't duplicate or replace its existing classes.
- Kari OS's scoped, optional skin: `src/app/kari-os.css`. Apply `data-kari-root` only to explicitly migrated screens.
- Runtime alone determines model/provider availability, completion, persistence, tool execution, memory state, RBAC, and telemetry. Presentation must not make up operational values.
- The current `public/brand/karen-mark.svg` and layout metadata remain untouched until the product-wide brand migration is separately approved and tested. The proposed Orbital-K logo remains a design asset, not a silent replacement.

## Approved visual constants

| Element | Baseline |
| --- | --- |
| Canvas | `#070708` |
| Panel | `#0d0e0f` |
| Card | `#121315` |
| Raised | `#1c1b1f` |
| Brand indigo | `#5e6bff` |
| Primary lavender | `#bec2ff` |
| Telemetry cyan | `#50d8e9` |
| Text | `#e5e2e3` |
| Muted | `#9a9da3` |
| Header height | `64px` |
| Left navigation | `252px` |
| Response context | `332px` |
| Stationary pinned dock | `276px` |
| Chat text width ceiling | `820px` |
| Card radius | `12px` |

Typography: Manrope for display, Inter for body, JetBrains Mono for technical values, with system fallbacks until licensed, locally served font resources are verified. Avoid global font imports and unverified remote font requests.

## Four distinct regions

1. **Navigation:** conversation history and product modules; scrolls independently.
2. **Chat:** messages and a bottom-attached composer; never scroll the entire app for each message.
3. **Response context:** shows artifacts associated with the selected response/message; no orphaned cards.
4. **Stationary dock:** user-pinned cards, independent scroll, no implicit cross-conversation authorization.

Cards should retain their source `conversation_id`, `message_id`, `run_id`, `artifact_id`, `revision`, `tenant_id`, lifecycle status, and permission scope. Moving a card does not clone its underlying data or override access checks. Server-authoritative persistence must confirm pins before the UI claims a save.

Default placement is adaptive by artifact type: text/simple results inline, substantial artifacts in response context, user pins in the stationary dock. Switching placement is a view operation. If the screen is too narrow, retain discoverable drawer/tab access rather than silently discarding card functionality.

Breakpoints: four regions at 1600px and above; three at 1280–1599px; two regions at 768–1279px; chat-first under 768px. CSS only defines baseline visibility; the future React owner must implement keyboard-accessible navigation/drawer entry points so hidden regions remain reachable.

## Chat functionality required before rollout

- Existing authenticated chat execution and response streaming remain authoritative.
- Message/card linkage survives reload, conversation branching, regeneration, and cancellation.
- Independent, keyboard-accessible scroll containers and focus restoration.
- Real provider status and degraded-mode disclosures; never hardcoded sample models, latency or "online" badges.
- Artifact loading, ready, stale, failed, canceled, restricted, and archived states.
- Approval and execution receipts for high-risk actions; server-side RBAC and audit preserved.
- Typed, schema-versioned artifact manifests rather than arbitrary plugin-generated HTML.
- Draft and panel state restoration with server-validated preferences, not fictitious saves.
- Responsive sheets, proper aria labeling, touch targets, contrast and reduced motion.
- Dark reference is approved. Light theme is provisional pending visual approval.

## Acceptance and proof

- Compare actual browser screenshots with the approved HTML fixture at **390, 768, 1024, 1440 and 1920 CSS px**; do not weaken thresholds to hide regressions.
- Run `npm run lint`, `npm run typecheck`, `npm run build` in `src/ui_launchers/Karen-AI-Theme`.
- Run relevant existing authenticated chat E2E and first-boot tests.
- Verify DOM focus, panel restoration, draft continuity, artifact provenance, RBAC and tenant isolation across pins.
- No critical layout change may ship while the desktop reference is replaced with an unapproved, simplified dashboard.

## KUI-001 change scope

This first PR introduces a scoped CSS contract plus root import and does **not** attach `data-kari-root` to existing routes. It is therefore designed not to alter any currently rendered screen. The next change must audit the actual active chat owner and test the full component integration before applying the skin.

## Verified current component ownership (repository audit)

- Product shell and navigation: `src/app/dashboard/page.tsx` (uses Radix sidebar primitives; dynamically mounts consumer chat).
- Conversation/session navigation adapter: `src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx`. Uses `SessionProvider`, guards active runs during navigation, and delegates chat execution to `KarenCopilotChat`.
- Runtime/model preference surface: `src/components/chat/KarenComposerRuntimeCatalog` (requested selection only, not proof of actual model execution).
- Chat execution display: `src/components/chat/copilotkit/KarenCopilotChat`, which must be audited before changing message rendering.
- Existing product mark: `public/brand/karen-mark.svg` and root metadata in `src/app/layout.tsx`. Do not silently overwrite until the full brand migration is approved.

**Next implementation slice:** audit the underlying `KarenCopilotChat` component and artifact rendering pipeline; add response-aware context and user-pinned dock as a separately reviewed change. Preserve `SessionProvider` as conversation-identity owner, and keep all persistence and action permissions backend-authoritative.

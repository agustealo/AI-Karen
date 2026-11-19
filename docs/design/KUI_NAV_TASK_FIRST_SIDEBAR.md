# KUI-NAV: task-first dashboard navigation

Status: source implementation under exact-head review; **not browser-certified**.

## Existing authority reused

- `src/app/dashboard/page.tsx` remains the authenticated view shell and owns navigation state, settings entry parameters, backend gates, and plugin execution mounts.
- `src/components/navigation/workspace-navigation-registry.ts` is the single owner of **static** sidebar view labels/order/icons. It does not enumerate or authorize plugins.
- `src/components/navigation/KariWorkspaceNavigation.tsx` renders the existing Radix Sidebar primitives, canonical session creation callback, current view selection, and mobile-drawer dismissal.
- `src/plugin_host/route-injector.ts` is the **sole authority** for backend-derived plugin sidebar contributions. Sidebar entries are passed through without inventing plugin availability.
- `src/components/chat/SessionProvider.tsx` is the existing session creation and authorization authority. A failed create remains an error and does not switch the active workspace.
- `src/app/kari-os.css` owns graphite/nav typography: Manrope for wordmark, Inter for navigation and captions, JetBrains Mono only for verified technical metrics. No new font download, theme palette, or sidebar framework.

## Information architecture

Default focus: Chat, Activity, Automations, My Tasks, Tools & plugins.
Secondary disclosure: Advanced tools → Agents / Jobs / Cron Jobs / Pocket TTS / registered plugin routes.
Persistent lower region: Personalize → Persona Studio / Growth; Application Settings; My Account; RBAC-gated Admin settings.

This is **progressive disclosure**, not feature removal. The five primary keys and every previously discoverable static view remain routed through the existing dashboard. The default selection and dynamically provided plugin view keys are not hardcoded into the renderer. Advanced and personal disclosures open automatically when an active destination is inside them.

The sidebar keeps Radix's collapsed icon/tooltips and mobile sheet. Its 252px expanded desktop target reuses `--kari-nav-width`; mobile remains accessible as a drawer. Navigation closes the mobile drawer only when a destination is selected, not when a disclosure expands. The session action asks the canonical provider to create a real conversation, never displaying a fake 'saved' acknowledgment.

## Functional and security limits

- UI cannot pick providers, bypass RBAC, enable plugins, infer readiness, fake history, or persist local preferences as server saves.
- Administration is rendered from existing authenticated `isAdmin()`, with backend authorization still required at `/admin`.
- Registry is static UX metadata; `usePluginRoutes()` remains the live plugin source.
- No new navigation search is shown because no verified search owner has been bound to that action.
- Typography uses existing fallback stacks if local Manrope/Inter/JetBrains Mono assets are unavailable; exact font-fidelity must be observed in an approved browser.

## Proof

```bash
cd src/ui_launchers/Karen-AI-Theme
npm ci
npm run lint
npm run typecheck
npx vitest run tests/navigation/workspace-navigation.test.tsx
npm run build
```

Run existing opt-in authenticated `e2e/ux-user-journeys.spec.ts` and other dashboard UX journeys against an approved KAREN host. Capture and manually inspect at 390, 768, 1024, 1440 and 1920 CSS px with real backend context. Confirm mobile drawer dismissal, navigation labels, active state, keyboard/focus, collapsed tooltip/expanded section, feature reachability, no PII in screenshots, and both dark/light mode. These real-browser results have **not been observed yet**.

### Five-viewport opt-in typography evidence

The existing `e2e/ux-user-journeys.spec.ts` now contains UX-16. On an approved
running KAREN deployment with a dedicated sanitized account, enable
`KAREN_NAV_VISUAL_ACCEPTANCE=true` and `KAREN_SANITIZED_ACCOUNT=true` alongside
the existing UX email, password, and approved base URL; execute:

```bash
npx playwright test e2e/ux-user-journeys.spec.ts \
  --config=e2e/playwright.config.ts --project=chromium --grep="UX-16" --retries=0
```

The test checks real computed Inter navigation typography, KAREN branding,
primary destination reachability and mobile drawer dismissal at 390/768/1024/
1440/1920 CSS px, and attaches an individual screenshot for each viewport.
Do not treat skipped, absent, or unreviewed browser artifacts as acceptance;
retain them privately and inspect for personal/tenant data before sharing.

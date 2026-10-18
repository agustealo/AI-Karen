# KAREN user-journey UX audit and evidence register

**Status:** audit protocol and initial executable browser smoke coverage committed; live application journeys not yet executed.  
**Owner:** frontend browser verification in `src/ui_launchers/Karen-AI-Theme/e2e/`.  
**Visual provenance:** [governed screenshot contract](../assets/screenshots/README.md).

## Why this exists

A screenshot proves appearance at a moment, not that an action worked. This audit connects each user goal to its action, expected result, observed result, screenshot, implementation owner, and reproducible test evidence. Never present an unexecuted journey as passing.

## Evidence contract

For each journey, the reviewer must record:

- **Deployment:** full target git revision, capture harness revision, URL/environment classification, sanitized test-account declaration, browser, viewport and timestamp.
- **Precondition:** verified live provider/backend status and account permissions. Do not silently substitute mocks, fixtures, fake responses, or canned text.
- **User action:** exact starting screen, controls clicked, input submitted and navigation path.
- **Expected result:** externally observable acceptance criterion, including persistence after refresh when relevant.
- **Observed result:** actual behavior, including visible errors and console/network failures; use `NOT RUN` before execution.
- **Evidence:** screenshot or video/trace attachment generated during the journey. A screenshot must show a settled state without personal data. Redaction must not obscure the defect.
- **Ownership:** canonical frontend component, API ingress, runtime service, or integration owner. Use precise file paths from the tested revision.
- **Classification:** `PASS`, `PARTIAL`, `FAIL`, `MISLEADING`, `NOT_CONNECTED`, `BLOCKED`, or `NOT_RUN`.
- **Issue/verification:** repro steps, relevant log correlation ID (secrets excluded), repair PR and rerun results.

Record genuine broken/loading-state screenshots **as defect attachments**, never as promotional imagery in `docs/assets/screenshots/`. Keep the canonical five-screen gallery under its existing manifest and governance rules. Do not create a competing screenshot capture pipeline.

## Priority journeys

| ID | User goal | Tested action | Expected result | Observed | Canonical starting owner | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| UX-01 | Open Karen for the first time | Open `/` while signed out on unconfigured deployment | Correct setup screen or actionable unavailable state | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/app/page.tsx` | Pending |
| UX-02 | Start a conversation | Sign in, navigate to Chat, send an ordinary prompt | One complete answer and truthful completion metadata | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx` | Pending |
| UX-03 | Recover interrupted streaming | Interrupt live response or simulate real transport loss in controlled environment | Explicit incomplete/error state, no fake completed answer or fallback text splice | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx` | Pending |
| UX-04 | Resume a conversation | Start a conversation, reload, reopen it | Correct messages and persisted session restored | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx` | Pending |
| UX-05 | Choose working intelligence | Open provider selector, choose a backend-reported available model, send message | Correct requested/actual provider identity and honest unavailable handling | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/chat/interface/ChatInput.tsx` | Pending |
| UX-06 | Find and manage agents | Navigate from dashboard to agents; inspect real running state | Clear purpose, state, available actions, feedback | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | Pending |
| UX-07 | Discover and inspect plugins | Navigate to plugin ecosystem and inspect connection/permission state | Genuine manifest/availability data; no inert actions | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/plugins/PluginOverviewPage.tsx` | Pending |
| UX-08 | Set up communications | Open Comms Center and inspect supported channel onboarding | Channel requirements, risks, connection state and next action are truthful | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/comms/CommsCenterPage.tsx` | Pending |
| UX-09 | Configure memory and models | Open settings and navigate to model and memory controls | Understandable defaults, reversible controls, confirmed persistence | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/settings/SettingsDialog.tsx` | Pending |
| UX-10 | Use Karen on mobile | Repeat UX-02 and UX-08 at narrow viewport | No clipped actions, usable input, functional sidebar, visible feedback | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | Pending |
| UX-11 | Operate without a mouse | Navigate chat/settings with keyboard and screen reader | Visible focus, meaningful labels, dialog focus management, accessible errors | NOT RUN | Shared UI components and tested screen | Pending |
| UX-12 | Trust the result | Inspect degraded/failed tool, model and persistence scenarios | Honest state, actionable recovery, no false saved/success indication | NOT RUN | Chat runtime and UI projections | Pending |
| UX-13 | Discover advanced controls | Open dashboard, identify primary destinations, expand Advanced tools | Clear core navigation; all advanced routes still reachable | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | Pending |
| UX-14 | Mobile navigation | Open sidebar on 390 x 844 viewport, reveal core and advanced destinations | Primary routes readable; advanced destinations accessible in mobile sheet | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/components/ui/sidebar.tsx`; dashboard | Pending |
| UX-14 | Navigate on mobile | Open sidebar at 390px, choose Messages & channels | Drawer closes and workspace remains available | NOT RUN | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | Pending |

### Defect entry format

```md
### UX-XX: Short user-visible problem
Severity: P0 / P1 / P2 / P3
Status: FAIL / PARTIAL / MISLEADING / NOT_CONNECTED
Revision and deployment:
Browser / viewport:
Precondition:
Action:
Expected:
Observed:
Screenshot/trace:
Reproduction:
Frontend owner:
API/runtime owner (if relevant):
Correlation ID (redacted):
Remediation:
Regression test:
Retest:
```

## Screenshot lifecycle and documentation reuse

1. Run the existing governed authenticated five-screen showcase capture against a live sanitized demo; keep its original manifest and security controls.
2. Verify target-revision attestation and inspect images at full resolution. Preserve only useful, settled, authentic product screens in `docs/assets/screenshots/`.
3. When a screen demonstrably supports a feature, link the **existing canonical screenshot path** in its relevant documentation. Explain what the image proves and its capture date/revision. Do not advertise that it proves end-to-end action success.
4. Capture journey-specific before/action/after evidence as test artifacts with the journey ID. Keep failures and temporary evidence out of the curated gallery.
5. Promote a new canonical screenshot only through the existing capture authority and provenance validation, after visual and privacy review.
6. Re-run the action at mobile and desktop widths. A visually pleasing desktop screenshot is not responsive proof.

**Currently permissible README illustrations:** existing verified `03-plugin-ecosystem.png` and `04-comms-center.png` with their historical attribution. The other three canonical screens must not be promoted until reviewed and valid at the new target revision.

## UX heuristics and pass conditions

Inspect each journey for: task language instead of backend jargon, first-action clarity, hierarchy and density, typography and legibility, visual consistency, actionable loading/error/retry states, permission transparency, keyboard/focus behavior, touch target usability, responsive layout, latency feedback, and durable persistence.

P0 means a core journey fails or displays fabricated success. P1 means a major task is unusable, misleading or undiscoverable. P2 means a significant usability/accessibility defect. P3 means polish. **No score is assigned without a measured run.**

## Run and evidence locations

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npx vitest run tests/api-stream-incomplete.test.ts
npm run test:e2e
# Real user-journey smoke: no mocked APIs; sign-in requires a sanitized account.
KAREN_UX_EMAIL='<sanitized-test-email>' \
KAREN_UX_PASSWORD='<sanitized-test-password>' \
KAREN_BASE_URL='<live-test-deployment-url>' \
KAREN_UX_TARGET_REVISION='<deployed-full-sha>' \
npx playwright test e2e/ux-user-journeys.spec.ts --config=e2e/playwright.config.ts
# The governed showcase capture needs its documented sanitized-demo
# variables and a real application deployment:
npm run showcase:capture
```

The mobile drawer dismissal smoke adds UX-14 (selecting a destination at 390px closes navigation). The navigation disclosure smoke adds UX-13 (primary routes and Advanced tools toggle). It is not yet live-tested. The executable smoke covers UX-01, UX-02, UX-04 (both user prompt and exact assistant reply after reload), the composer portion of UX-10, keyboard focus for UX-11, and a controlled failed-transport scenario for UX-12. A deterministic API stream-contract regression now covers content followed by EOF, a premature DONE sentinel, and a truncated terminal record in `tests/api-stream-incomplete.test.ts`. It asserts no completion callback, explicit `CHAT_STREAM_INCOMPLETE` error provenance and a real terminal-completion control case. This synthetic fault is unit-test evidence, **not** an authenticated browser journey or product screenshot. Browser-level partial-stream interruption, memory/persistence degradation, and complete mobile response remain outstanding. UX-04 verifies the exact rendered assistant reply after reload but does not prove cross-device sync. UX-12 aborts the stream connection before a response, so it is a truthful transport-failure proof rather than a partial-stream splice proof. UX-11 verifies composer keyboard focus only; it is not a complete screen-reader audit. Execution artifacts contain screenshot plus structured action/expected/observed metadata. Screenshots are evidence, not permission to promote the image to the README. The credentials are never logged or included in attachments.

The default generic Playwright config uses `KAREN_BASE_URL` and saves failure screenshots/videos/traces. The governed showcase uses `KAREN_SHOWCASE_BASE_URL`, a sanitized account, and revision attestation. See [capture instructions](../assets/screenshots/README.md) before invoking it.

### Explicit limitations of this audit pass

The repository was inspected, but no authenticated browser was launched against a live Karen deployment for this report. Therefore every journey above remains **NOT RUN**. There is no new screenshot, no measured pass rate, and no evidence of current broken behavior from this pass. Existing screenshots remain historical, not fresh release signoff.

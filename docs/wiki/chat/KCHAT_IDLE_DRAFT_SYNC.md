# KCHAT: Quiet idle composer and authenticated draft synchronization

## Observed behavior and source owner

A healthy, idle chat previously issued \`GET /api/conversations/{conversation_id}/draft\` every ten seconds. This originated in \`useKarenPersistedDraft\` under the CopilotKit controlled-chat frontend. It was a repeated authenticated read, not a new prompt, inference request or transcript write.

The canonical server authority remains \`ConversationRuntimeGateway\` and the tenant/user-scoped \`ConversationRepository\`. The API route is thin. CopilotKit submits model requests only on an explicit user gesture after the existing revision-fenced draft-save-and-clear protocol.

## Change

The frontend no longer polls healthy drafts. A draft is read on conversation mount, when focus returns, when the page becomes visible, or upon a same-origin \`BroadcastChannel\` announcement from another tab.

The channel name is scoped to the conversation ID, and messages contain **only** \`{ revision }\`. Never broadcast draft text, tokens, credentials, user IDs, tenant IDs or model prompts. A higher revision prompts a fresh authenticated server read; the frontend never treats peer-provided data as a saved receipt.

Both successful revision-fenced writes, including a safe empty-draft clear before submit, announce their server-confirmed revision. The CAS protocol, unknown-outcome GET readback, conflict state, unsaved-edit guard, session cleanup and explicit submit gate are unchanged. Browsers without \`BroadcastChannel\` use focus/visibility refresh.

The existing ten-second recovery timer remains active **only** for authenticated draft requests that returned a temporary HTTP 503. It does not retry 401/403/404, silently resolve 409 or replay uncertain CAS mutations.

## Invariants and limitations

- Current-state reading, policy and model execution remain server authorities, never UI fallbacks.
- Healthy visible idle composers perform no periodic reads or writes.
- Local dirty text is never overwritten by a focus or cross-tab notification.
- Unmounting, logout or changing conversation closes the channel and removes listeners; no draft text goes into browser storage.
- Cross-tab notifications are best-effort and only work between compatible same-origin tabs. Changes on other devices become visible on a focus/visibility reload. Exact real-time cross-device updates would require a separately governed authenticated backend event channel.
- The backend still checks tenant, user and conversation ownership for every read and write.
- Request logs must be interpreted by method and route: a draft GET does not prove a prompt or a provider execution.

## Acceptance

1. \`cd src/ui_launchers/Karen-AI-Theme && npx vitest run src/components/chat/copilotkit/useKarenPersistedDraft.test.tsx\`
2. \`cd src/ui_launchers/Karen-AI-Theme && npm run lint && npm run typecheck\`
3. Confirm local browser Network tab: a healthy idle composer has **one initial draft GET and no recurring draft requests for 60 seconds**. Health probes are out of scope.
4. Verify focus, hide/show, same-origin second tab, stale revisions, unsaved local edits, 409 conflicts, unavailable storage, submit/CAS clear, logout and conversation changes.
5. Correlate a real user submission with exactly one SDK run, authorized backend execution and committed transcript; observe **zero** provider inference on idle draft refresh.
6. Require exact-head Main Quality, relevant frontend and chat CI, independent review and deployment acceptance before merge. Do not accept an older Vercel preview as proof of the candidate SHA.

This patch does not add another draft store, backend polling service, or model routing decision. No production behavior is claimed verified by a source-only change or a simulated UI test.

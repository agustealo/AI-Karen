# KCON-770 nine-case fault acceptance: implementation contract

Status: SOURCE TESTS MERGED / AUTHENTICATED BROWSER NOT_RUN (2026-11-09). PRs #710–#713 landed executable cases 01–09; this does **not** constitute signed-in browser acceptance or real failure screenshots. Keep KCON-770 unchecked. The canonical Main Quality Gate now explicitly invokes existing runtime/presentation/tool/persistence owners; frontend Vitest covers controlled chat and presentation components.

## Existing owners

- Browser: `src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts`, using `./fixtures/verified-search-deployment` and `./fixtures/approved-karen-login`.
- SDK state: `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotControlledChat.tsx`; existing `tests/karen-copilotkit-controlled-chat.test.tsx`.
- Runtime SSE: `src/ai_karen_engine/api_routes/chat/runtime.py`; existing `tests/core/runtime/test_chat_sse_error_contract.py`.
- CI: `.github/workflows/main-quality-gate.yml` (source contracts only); existing opt-in authenticated Playwright dispatch must remain separate.
- Ledger: `docs/capabilities/copilotkit-execution-plan.md`.

## Required nine-case matrix

| Case | Injection boundary | Required result | Proposed test |
|---|---|---|---|
| 01 SDK onRunFailed | existing controlled chat SDK lifecycle | generic visible failure, no fabricated assistant, no secret disclosure | `test_sdk_run_failed_shows_honest_error` |
| 02 runAgent rejection after accepted send | existing SDK send/draft owner | exactly one submitted user turn, no draft resurrection, preserve newer edits | `test_accepted_send_rejection_never_resends` |
| 03 contradictory SSE terminals | existing `_sse` runtime owner | first terminal wins; exactly one DONE; no late content | `test_first_terminal_is_final` |
| 04 empty model text | canonical runtime outcome | no successful empty assistant, honest failure/retry | `test_empty_model_output_is_not_success` |
| 05 missing image | canonical presentation validation | no fabricated image; source-backed text remains when verified | `test_missing_image_does_not_claim_rendered_media` |
| 06 unsupported card | presentation registry/renderer | explicit unsupported state or safe source-backed text; no fake card | `test_unsupported_presentation_is_not_success` |
| 07 partial run/disconnect | runtime streaming + SDK | partial text never recorded as completed answer; retry does not duplicate user turn | `test_partial_stream_disconnect_is_not_complete` |
| 08 persistence failure | canonical conversation persistence | visible save failure, no false saved/history receipt, no cross-thread recovery | `test_persistence_failure_is_visible` |
| 09 unavailable tool | governed tool execution | honest unavailable result, no invented observation or provider success | `test_unavailable_tool_does_not_fabricate_answer` |

The executable source tests for 01–09 now exist in the nearest **existing** owners. The original case-08 test proves fail-closed **persona preference persistence**, not a live failed conversation transcript write. Subsequent #736 and #737 source fixes guard AG-UI and non-streaming HTTP transcript failure receipts, but source tests still do not prove an actual database fault. The protected case-08 browser path must use a real, operator-approved backend-side transcript failure and the existing owner-scoped durable run status plus observed-event journal. A generic provider/SDK failure is not an acceptable substitute. Cases 01–03 also reuse the earlier #706–#708 source fixes. Browser scenario must use real authenticated backend and an operator-controlled fault mechanism that is already authorized in the runtime. Never inject failures by intercepting network requests in the release proof, editing production data, or bypassing RBAC.

## CI and browser evidence contract

`main-quality-gate.yml` now executes the relevant backend runtime, presentation, time-tool, SSE and persona-persistence tests in its existing jobs; the existing `frontend-quality` job runs the controlled-chat and presentation Vitest tests. Do not add a second workflow or duplicate runner. Main Quality Gate proves source behavior only. The real signed-in failure scenario belongs to the existing opt-in Playwright suite, not an unauthenticated mocked CI browser.

1. Deploy the exact reviewed PR/head revision to an approved environment; record full 40-character SHA and target origin. Require release HTTPS, no URL credentials, and the existing `/api/deployment-revision` equality check.
2. Require canonical `/api/health` to return `{ "status": "ok", "backend_ready": true }` before sending credentials. Use approved `KAREN_E2E_AUTH_STATE` or `KAREN_UX_EMAIL` and `KAREN_UX_PASSWORD`; never log or commit them.
3. Set `KAREN_CHAT_BOOT_ACCEPTANCE=1`, `KAREN_BASE_URL`, `KAREN_CHAT_BOOT_REVISION`; run the existing Playwright consumer boot spec via its existing release dispatch. Do not set local and release modes together.
4. Sign in through `signInApprovedKaren` when no approved storage state exists. Navigate to `/dashboard`, open Ask Karen if needed, verify `karen-copilot-consumer-chat` and `karen-copilot-controlled-chat`, then create a new conversation through the UI.
5. With an authorized, reproducible backend-side **transcript-write** failure condition, submit a unique non-sensitive prompt via the real composer. The protected `copilotkit-failure` dispatch requires `KAREN_KCON770_EXPECT_TRANSCRIPT_FAILURE=1`. Verify exactly one real CopilotKit run POST, capture only its bounded run ID (never log prompt/request body), and assert a visible generic failure, zero fabricated assistant successes, no raw exception/secret, no duplicate user turn and no restored stale draft. Using the signed-in browser, read only the exact owned run's status and observed event journal through existing same-origin endpoints: the run must be `failed`, the complete journal must show exactly one `RUN_ERROR` carrying `CHAT_TRANSCRIPT_NOT_PERSISTED`, and it must contain neither `RUN_FINISHED` nor a saved assistant execution receipt. Missing journal or another failure code means NOT_RUN/FAIL, not case-08 PASS.
6. Capture a **redacted** screenshot of the visible error state, plus test result, deployment SHA, correlation ID (only if safe), conversation ID (redacted in publicly shared reports), failure category, UTC timestamp and replay behavior. Keep raw authenticated Playwright screenshot, storage state, trace and video **outside public GitHub artifacts**. Do not commit authenticated screenshots.
7. Reload the same thread. Re-read the same owned run status and observed event journal, using its original run ID, and verify the original failure code and absent saved assistant receipt remain unchanged. Verify canonical history remains truthful; do not accept a newly generated reply as evidence of the original failed run. Record screenshot proof as VERIFIED only when the approved evidence is accessible to the reviewer.
8. Execute all nine matrix cases, recording PASS/FAIL/NOT_RUN with real environment and provenance. Missing authorized fault controls mean NOT_RUN, never PASS.
9. Update only the existing KCON-770 ledger row and append one changelog line after source merge. Check KCON-770 only when all nine cases and the signed-in browser screenshot/replay are reviewed and passing.

## Acceptance gates

Source: existing backend/frontend tests, architecture checks, Main Quality Gate and exact-head checks green. Browser: matching deployed SHA, authenticated real backend, genuine failure reproduced, visible screenshot proof, safe replay, and all nine cases passing. This document alone satisfies **none** of those gates.

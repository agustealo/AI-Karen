# CK consumer UX adversarial findings: clocks, timers and execution rail

**Observed consumer report:** 2026-10-30. **Status:** remediation in progress, NOT consumer acceptance.

## Reproducible user-facing failures

1. The request **"Show a live time"** returned a static UTC timestamp in assistant prose. The existing `time.observation` presentation displays a formatted snapshot, not a ticking clock. A timestamp does not meet a *live* display promise.
2. **"Start a 10 min timer"** produced a completion-sounding statement, but no timer artifact, deadline, durable scheduler receipt or visible countdown was shown. Subsequent replies asserted the timer was still active and its display hidden, despite no verified timer state.
3. No reminder was delivered. Do not interpret model prose as a queued reminder. The existing time-query alarm handler discloses `storage: in_memory`, `durable: false` and `scheduler_status.integrated: false`; its definition management cannot substantiate background delivery.
4. The active `/dashboard` still renders `assistant-ui/KarenAssistantChat`; an unmounted CopilotKit candidate is not consumer UX progress visible on the dashboard.
5. `ConversationContextRail` was mounted only in the assistant-ui renderer, not the CopilotKit candidate, and its `hidden ... xl:block` CSS hides it on smaller widths. A blank rail must never be filled with fabricated provider/tool/memory activity.

## Canonical ownership and required repair

| Contract | Canonical owner | Mandatory evidence |
| --- | --- | --- |
| Clock observation | governed time-query capability via ChatRuntime | authorized timestamp, source clock, timezone and observation instant |
| Truly live clock | client presentation derived from a verified clock observation | visible ticking clock, correct timezone, resync and stale/error state, no inference on every tick |
| Timer create/status/cancel | authorized runtime action and durable scheduler | tenant/user-scoped timer ID, persisted deadline, durable worker admission, status after reload, cancellation |
| Reminder delivery | existing governed scheduler/notification channel | delivery destination, permission, delivery receipt and explicit undelivered/failed state |
| Conversation intelligence | existing `ConversationContextRail` | saved backend execution receipts, no model-side guessed metadata |
| CopilotKit UX | existing CopilotKit v2 SDK | integrated active chat, history, controls, native slots, responsive rail, keyboard/a11y and consumer screenshot proof |
| Deployment proof | existing main-only browser workflow | exact running SHA, authorized principal, screenshots reviewed and passing Playwright |

## Fail-closed timer acceptance

A timer request must never receive "started", "running", "hidden", "will notify you" or "reminder sent" as a factual status unless a matching tenant-owned scheduler/delivery receipt exists. No in-memory clock, model text, user-visible animation or browser timer substitutes for durable execution. Where the scheduler is not available, clearly report **not scheduled** and do not claim a reminder.

Required scenarios:
- Create exactly one 10-minute timer with persisted `deadline_at` and a stable scoped ID; duplicated requests cannot create duplicate timers.
- Refresh or reconnect, read the same backend deadline, and show the remaining interval accurately.
- Pause/stop/cancel only through an authenticated action, with a backend status receipt.
- Verify authorization across user, tenant and conversation boundaries, expiry with the browser closed, and backend restart recovery.
- Request a reminder without approved notification destination: fail visibly and do not imply delivery.
- Notification delivery: differentiate scheduled, dispatched, delivered, failed and unknown; no fake delivered toast.
- Timer rendering after an expired or missing job must show expired/unavailable, not "still active".
- Current time: use a live observation-backed clock; do not label a static `time.observation` as a live clock.

## Candidate rail work on this branch

The existing context rail is now mounted in the gated CopilotKit chat shell. The only metadata it may receive comes from the backend-attested `karen.execution_receipt.v1` replay. With no receipt, it reports the absence rather than inventing steps. This does **not** yet prove all rich stream events or live UI parity.

## Cutover gate

Do not swap `/dashboard`, delete assistant-ui, claim timer/reminder support, or promote consumer readiness until the timer execution contract, active CopilotKit browser parity, native layout/rail at desktop and mobile widths, persistent rich replay, persona, preferences, voice and truthful model receipts have independent exact-revision proof.

**This document is evidence and acceptance criteria, not an implemented timer scheduler.**

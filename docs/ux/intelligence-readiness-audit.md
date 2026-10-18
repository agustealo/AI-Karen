# KAREN intelligence readiness: adversarial acceptance gates

**Status:** NOT SIGNED OFF. Transcript observation is user-supplied, not a reproduced browser execution. This matrix is a release gate, not a claim that any scenario now passes.

## Evidence and failure classes

| ID | Real user interaction | Correct observable response | Owner | Current proof |
| --- | --- | --- | --- | --- |
| INT-01 | `Hello` | Natural greeting, optional offer of help; no nonsensical intent clarification | Prompt contract + CORTEX conversational intent | NOT RUN |
| INT-02 | `My name is Zeus` | Acknowledge the just-supplied user statement as conversational information; never deny it for lack of durable storage | CORTEX intent + runtime evidence | Unit contract exists; live NOT RUN |
| INT-03 | `What's my name?` after INT-02 | `Zeus` from scoped user evidence; indicate uncertainty or storage degradation only if relevant; never invent a durable save | NeuroRecall + RuntimeEvidenceResolver + runtime prompt | Unit contract exists; live NOT RUN |
| INT-04 | `Tell me about me` | Summarize only supported user facts; distinguish recent statement, confirmed durable fact and unknowns; no fabricated biography | Runtime evidence sufficiency + prompt assembly | NOT RUN |
| INT-05 | `Share please` following a personal-summary offer | Resolve referent from authorized conversation; if unavailable ask one narrow question rather than produce unrelated personal information | CORTEX discourse + history/context | NOT RUN |
| INT-06 | `What time is it in NYC?` | Obtain authoritative clock and named-location timezone; avoid model-generated time guesses and double timezone conversion; log tool provenance | CORTEX time-intent + governed tool execution | NOT RUN |
| INT-07 | Failed or rejected durable history | Fail closed on unauthorized object scope; on dependency failure only use bounded, ownership-confirmed provisional user turns; never claim memory persisted | RuntimeEvidenceResolver + canonical conversation gateway + RuntimePolicy | Unit tests on PR #480; latest-head CI pending |
| INT-08 | Small local model invents `you are an AI created by DeepSeek` | Never present an unsupported personal identity/occupation claim as user fact; a fluent completion is not provenance | Runtime grounded personal-answer contract + provider capability routing | NOT RUN |
| INT-09 | Output token cap during personal summary | Clearly label incompleteness, preserve answer provenance and useful supported facts; avoid sprawling generic filler | Runtime completion metadata + UI | NOT RUN |
| INT-10 | Repeat all above with configured local primary and at least one stronger available model | Measure correctness per model; no user-visible fake provider selection, no hardcoded model exceptions | Provider registry + router + runtime | NOT RUN |

## Concrete acceptance protocol

1. On an approved, sanitized authenticated tenant, capture exact user messages, request IDs, conversation IDs (redacted externally), CORTEX intent decisions, prompt-contract versions, authorized evidence, source/ownership status, chosen provider/model, response source, terminal events, and memory/persistence receipts.
2. Run every case in a fresh session, an existing session, after reload, and with durable-history failure injection; use approved isolated data for cross-tenant denial.
3. Verify evidence-level assertions independently of model wording: neither a client assertion nor a generated assistant claim may become a server-confirmed memory. For personal factual claims, the output must be supported by a same-scope user statement or canonical durable evidence.
4. Test `deepseek-r1:1.5b` as configured if available. Report its failures separately from orchestration failures. Do not claim every model can satisfy complex reasoning requirements. Runtime chooses only from real registry availability and the user's configured/allowed routing policy.
5. Keep `Hello`, disclosure, recall, time, follow-up resolution, and grounded summary as distinct intent contracts. Do not patch each with new keyword responders or route-level canned answer text.
6. Require screenshot, observed answer, API/event trace, evidence IDs and original source, model metadata, expected versus observed result, and defect owner before marking a case PASS.
7. Re-run the existing backend/context/RBAC/security gates, frontend chat tests, and live chat burn tests. Passing source tests does not substitute for a successful authenticated end-to-end run.

## Decision

**Release readiness: NO.** In the supplied transcript, Karen confuses greeting with clarification, denies an immediate user statement, answers NYC time incorrectly, and invents a personal biography when asked to continue. Partial retrieval failures and output-token truncation further degrade trust. Those are P0 user-trust defects even when provider dispatch, memory stores, persistence status, and infrastructure health report success.

## Architecture

One authority for each concern: CORTEX classifies/decides; RuntimeEvidenceResolver coordinates authorized evidence with NeuroRecall and the conversation gateway; governed prompt assembly instructs the selected provider; provider registry/router decides availability; runtime validates completion/persists/audits; UI displays backend truth. Never let UI or ingress invent verified personal memory or a model response. No packaging or consumer signoff without human review.

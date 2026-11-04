# KCHAT native streaming contract

## Objective

One authenticated user gesture must produce one durable canonical chat turn.
On a streaming-capable model endpoint, the consumer must see **actual model
deltas while generation is still running**, not one completed string disguised
as a stream. The runtime must not claim successful generation, attribution or
persistence before an actual verified terminal receipt.

## Authority and data flow

1. **CopilotKit composer** accepts one explicit Submit gesture. The existing
   revision-fenced draft flush and clear must succeed first. It never selects
   providers, constructs hidden prompts, or fabricates a run receipt.
2. **CORTEX and RuntimePolicy** determine intent, tool/agent eligibility,
   model constraints, identity and tenant scope.
3. **ChatRuntime** assembles one governed prompt and creates one
   `ExpressionTask`. A private in-process `token_sink` carries model deltas
   only for that request and must never be serialized, journalled, persisted or
   accepted from the HTTP request.
4. **ExpressionGateway.generate** remains the sole engine choice and ordered
   fallback authority. **OpenAICompatibleEngine.generate** executes the
   already-selected registered endpoint, using the new canonical SSE transport
   only if the endpoint declares streaming support.
5. **ChatRuntime._run_simple_stream** owns the bounded event queue and
   cancellation. It yields deltas before generation completes, validates that
   the accumulated consumer-visible text matches the final model result, and
   updates actual model/provider metadata only on the verified result.
6. **AG-UI and CopilotKit** render that backend event stream; the backend
   remains authoritative for turn completion, persistence and replay.

No parallel runtime, second prompt builder, client-side model fallback,
unauthorized tool call, or duplicate provider registry is permitted.

## Security and failure rules

- The SSE transport rejects invalid JSON/framing, mismatched model receipts,
  tool calls, non-assistant roles, unbounded output, an incorrect content type,
  missing finish reason and missing `[DONE]`.
- A provider can fail and permit an already-authorized configured fallback
  **before** any token has reached the user.
- **After one visible token**, switching to another model is forbidden.
  The stream fails with `partial_provider_stream_unverified`, and the user
  may retry explicitly. Never splice two providers' output into one answer.
- No aborted or unverified wire stream becomes a completed response,
  persisted transcript, recalled memory, or execution success.
- A legitimate `finish_reason=length` follows the established degraded
  `output_truncated` policy and is never labeled an ordinary complete answer.
- Cancellation/disconnect cancels the bounded producer and closes the
  provider HTTP streaming context. Do not swallow `CancelledError`.
- Provider HTTP exceptions may contain private request URLs and content.
  Observability emits only bounded error codes and exception classes.
- A non-streaming endpoint retains the established full-response behavior,
  with honest source attribution, not fabricated intermediate chunks.

## Metrics and consumer release gate

Measure `first_token_latency_ms` at the runtime from the start of direct
generation to the first actual accepted model delta. Also track CORTEX,
memory, prompt assembly, provider generation, persistence and total response
latencies by correlation ID. Log no transcript or secrets.

CI unit tests alone cannot demonstrate actual user experience. Release
requires a live authenticated browser trial with an installed **real** model:

1. Confirm the deployed backend SHA equals the expected merged `main`.
   Verify the API database is the one that contains the composer-draft schema,
   RLS, grants and durable replay support.
2. Type a novel one-line generative prompt and press Enter once. Exactly one
   canonical draft CAS submission, one AG-UI run and one user turn must occur.
3. Confirm the first visible model delta arrives **before** the last backend
   model frame, with a measured nonzero TTFT and the same full answer on REST
   and streaming paths. Only a verified terminal receipt may attribute the
   actual provider/model.
4. Interrupt the stream after a first delta. Confirm no second model answers,
   no completed transcript, no false healthy execution, and safe retry.
5. Repeat with weather from an explicit location. Source facts must come from
   authorized timestamped weather evidence; on outage, preserve a bounded
   unavailable result without hallucinated readings.
6. Ask `time` and `what is time?`. The first is the current-time capability
   with a verified and labeled timezone. The second is generative chat.
7. Reload a completed conversation and verify messages, model receipt and
   presentation integrity from the canonical governed history. An unsupported
   rich-history snapshot still fails closed with a safe internal reason.

Exact-head proof:

```bash
python -m compileall -q src
pytest tests/core/model_runtime/test_provider_execution_stream.py \
  tests/core/expression/test_expression_stream_fallback_integrity.py \
  tests/core/expression/test_openai_engine_native_token_stream.py \
  tests/core/runtime/test_native_expression_token_delivery.py -q
```

The native stream integration depends on the transport in PR #637.
A green parser test **is not** proof that the ChatRuntime/CopilotKit user
path actually streams. Do not mark consumer readiness green until the
authenticated browser trial passes on the deployed SHA.

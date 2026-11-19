# KCHAT-SMOKE-06: canonical chat terminal integrity across transports

## Observation and source owner

The authenticated real-Ollama first-boot proof at main
`38d14aaaaf2ac6822977a24e861ec01f0ecbcdfb`
passed provider selection, verification, stream/nonstream durable lineage,
and two transcript commits for each verified execution.

This proves a real runtime path, **not** every browser transport's correctness.
Source inspection found that `/api/chat/stream` used its own fail-closed
`_sse` wrapper, while Copilot Assist SSE, legacy SSE/NDJSON, and the chat
WebSocket forwarded raw `ChatRuntime.execute_stream` chunks independently.
A status-only return or upstream error could produce a transport close without
the canonical ERROR, and a post-terminal COMPLETE or CONTENT could be forwarded
after a previous ERROR or COMPLETE. The NDJSON adapter also emitted `done`
after any normal end, even without a verified terminal.

## Correction

The only owner of runtime event serialization/terminal integrity is
`src/ai_karen_engine/api_routes/chat/runtime.py`. Its
`_terminalized_chat_json_events` is used by canonical SSE, Copilot SSE,
legacy SSE, legacy NDJSON and the WebSocket. It forwards runtime metadata
without fabricating provider choices, model content, memory writes or receipts.

The first `complete` or `error` event is final. Exception, invalid JSON
serialization, or a nonterminal end become one safe correlated ERROR.
Cancellation is not converted to success. NDJSON emits an additional
transport-level `done` only after `complete`, not after `error`.
SSE `[DONE]` denotes wire closure, **not** successful model completion.
The existing runtime/HTTP routing authority and tenant identity guards remain.

Import-level smoke also found an eager compatibility import in
`services/streaming/__init__.py`: importing the WebSocket transport pulled
the retired `AsyncStreamProcessor` and optional formatting metrics, causing
`ModuleNotFoundError: psutil` during the lean Chat System Burn test collection.
The existing legacy symbol remains available on explicit access, but is now
resolved lazily. This changes no runtime execution policy or authorization.


## Deep smoke / proof

`tests/core/runtime/test_chat_transport_terminal_parity.py` asserts the
same event types and terminal count across five transports for status-only
return, upstream failure after partial content, ERROR followed by a false
COMPLETE, COMPLETE followed by unverified late CONTENT, malformed JSON
metadata, and fully empty runtime output. It denies secret leakage in frames.

Both `Chat System Burn` and `Main Quality` run this suite at exact head.
Current real-model Ollama CI, durable PostgreSQL transcript/recall tests,
routing-policy, provider admission, and First-Boot remain separate required
proofs. This source repair does not claim a new production deployment or
fresh browser acceptance.

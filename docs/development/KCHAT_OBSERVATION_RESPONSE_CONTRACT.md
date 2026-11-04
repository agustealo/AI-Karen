# KCHAT observation response and latency contract

## Ownership

CORTEX decides whether a request is `time.current`, `search.weather`, or another intent. ChatRuntime authorizes the action and the canonical DirectCapabilityExecutor obtains an actual time/weather observation. `ExpressionGateway` is the **only** model-generation owner. The canonical `ResponseValidator` accepts or rejects generated presentation text.

A model does **not** become the authority for a clock value or meteorological reading. A model can explain a verified observation but cannot invent a temperature, timezone, forecast, timestamp, source URL, provider identity, or completion receipt.

## Fast clock behavior

For an already-classified `time.current` request whose exact user prompt is a short clock request (`time`, `current time`, `time now`, or their plain-language question equivalents), return the authorized clock observation immediately. The metadata must identify the result as a source observation with null actual model; it must **not** masquerade as an LLM reply.

Richer time and weather requests can use grounded ExpressionGateway generation, but only from verified tool/plugin attempts and bounded observation fields. Keep the presentation and REST/AG-UI stream content equivalent. On a model timeout or validation rejection, use the verified observation, not a fabricated answer.

## Runtime budget

`KARI_OBSERVATION_SYNTHESIS_MAX_OUTPUT_TOKENS`: default 96, range 16 through 512. The observed model must also respect the authorized per-request output budget.

`KARI_OBSERVATION_SYNTHESIS_TIMEOUT_MS`: default 6000, range 500 through 30000. The allowed model time is also capped by the authorized CORTEX decision budget. No extra retries or synthetic model text are permitted after the deadline.

The full long-form chat budget remains separate. Do not apply these short observation bounds to ordinary conversations or graph workflows.

## Privacy and response correctness

The grounded response validator rejects internal route labels (`time.current`, `search.weather`), continuity-candidate language, hidden prompt/decision mentions, unsupported observations and invented source URLs. The internal metadata can remain in the governed trace, never in the visible answer. A rejected model response cannot claim a model completion.

## Proving it

- `pytest tests/core/runtime/test_grounded_observation_synthesis.py tests/core/runtime/test_grounded_observation_adversarial.py -q`
- `pytest tests/architecture/test_observation_synthesis_budget_config.py -q`
- `python -m compileall -q src/ai_karen_engine/core/runtime src/ai_karen_engine/services/response`
- Exact-head Main Quality Gate, Chat System Burn, REST/AG-UI parity and browser validation.

Acceptance requires authenticated single-submit behavior, observed first response time for `time`, a localized timezone or explicitly labeled clock source, measured weather from the allowed live provider, an honest no-data response on weather failure, and a full real-model answer for a normal generative request.

CI does not establish the deployed local Docker timezone, installed LLM, migration state or network reachability. Verify those separately with the live host and exact deployed commit receipt.

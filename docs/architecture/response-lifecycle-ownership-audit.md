# Canonical response lifecycle ownership audit (M0)

Status: **audit / no execution-path migration authorized by this document**.

## Existing authorities

| Concern | Current location | Proposed disposition |
| --- | --- | --- |
| Request intent, evidence needs | `core/cortex/executive.py` | Retain: decides only |
| Evidence resolution, tenant scope | `core/runtime/evidence_resolver.py` | Retain: authorized evidence |
| Evidence sufficiency | `core/runtime/evidence_sufficiency.py` | Retain: guards personal assertions |
| Final runtime execution and response metadata | `core/runtime/chat_runtime.py` | Retain: single execution authority |
| Response presentation | `services/formatting/ResponseFormattingClass/Engine.py` | Retain and audit all transformations |
| Public presentation import | `services/formatting/response_formatting_engine.py` | Retain as facade |
| Pretty layouts | `services/formatting/pretty_output_layer.py` | Keep behind audited display-only contract |
| Output schema | `core/runtime/prompt/output_contract.py` | Reuse typed contract |
| Generated response hygiene | `core/errors/response_validation.py` | Retain; must not censor legitimate speech |
| LangGraph formatter | `core/langgraph_orchestrator/formatting/response_formatter_pipeline.py` | Migrate to runtime-approved adapter |
| Agent composers | `agents/agent_response_composer.py`, `agent_medusa/arbitration/response_composer.py` | Audit; no independent final response authority |
| Long-form policy | `services/formatting/response_policy_enforcer.py` | Audit expansion and evidence preservation |
| Consumer renderer | `ui_launchers/Karen-AI-Theme/src/components/chat/` | Backend metadata truth only |

## Confirmed hazards

1. LangGraph imports a shared `ResponsePolicyEnforcer` and also defines a **different, same-named local class**, shadowing the import. The local implementation filters envelope keys and truncates content; the shared implementation governs article expansion. They must not be mechanically replaced with each other.
2. Shared long-form policy contains a synthetic `_fallback_expand` implementation, despite `allow_template_fallback=False` by default. This must never be authorized for evidence-grounded outputs. Audit call sites and configuration before deletion.
3. `ChatRuntime._grounded_personal_response` joins raw `attribute: value` strings, causing redundant presentation of birthplace and origin. A new *presentation-only*, evidence-preserving composer must consume previously authorized facts, not query independent memory or choose a provider.
4. Formatting presentation functions can modify text/citations. The final lifecycle must validate transformations against typed output and provenance.
5. Streaming and HTTP both route through canonical ChatRuntime, but the guarantee that unverified factual output is never emitted must be tested at the emission boundary.

## Authority convergence contract

CORTEX decides requirements. Runtime retrieves and authorizes evidence, composes content and chooses execution. A single presentation engine operates **after** factual synthesis, without adding claims. Response integrity validates before release. Transports only serialize typed runtime results.

Never use formatting to infer a missing birthplace from origin, merge distinct stored memory records, bypass tenant access, or invent family biography. Do not send failed personal recall to a general LLM as a fallback.

## Next implementation slices

- **M0 proof:** Inventory import/call sites and classify active versus dead/compatibility code, including all LangGraph, Medusa, service and UI consumers.
- **M1:** Reuse or extend existing output contracts, define allowed transformations, and prove response metadata stability.
- **M2:** Extract evidence-preserving profile synthesis from ChatRuntime, deduplicate same-value birthplace/origin only in output, preserve differing values and conflicts; test cross-tenant and consent failure.
- **M3+:** Migrate LangGraph/agents, validate streaming/final claim integrity, and retire dead implementation only after reference audits.

## Required proof

```bash
python -m compileall src
pytest tests/architecture/test_response_lifecycle_ownership_contract.py -q
pytest tests/core/runtime/test_evidence_sufficiency.py -q
ruff check src tests
mypy src
```

Also require exact-head Main Quality Gate and Chat System Burn before merging and live user-facing verification before claiming hallucinations fixed.

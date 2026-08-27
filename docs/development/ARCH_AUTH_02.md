# ARCH-AUTH-02 — Authority and Vocabulary Closure

Status: active convergence contract

## Objective

Make KAREN's live execution graph match the canonical architecture:

```text
request
  -> Runtime lifecycle
  -> CORTEX cognitive decision
  -> RuntimePolicy authorization
  -> AuthorizedExecutionPlan
  -> Runtime execution
  -> governed memory/telemetry side effects
```

No subordinate component may invent cognition, authorization, provider choice, memory scope, or workflow semantics.

## Canonical vocabulary

### CORTEX

CORTEX is KAREN's cognitive executive. It decides what cognition is desirable and returns typed cognitive intent. CORTEX does not execute RuntimePolicy, providers, memory persistence, tools, plugins, LangGraph, or AgentMedusa.

### RuntimePolicy

RuntimePolicy is the authorization authority. It decides what requested capabilities, reasoning modes, resources, providers, tools, and side effects are allowed under tenant, identity, permission, risk, runtime-level, and budget constraints.

### Runtime

Runtime owns the request lifecycle and executes the AuthorizedExecutionPlan. Runtime may validate executability and compose authorized capabilities, but it may not invent a reasoning mode or broaden authorization.

### Soft Reasoning

The term **Soft Reasoning** is reserved for the Zhu et al. research-derived reasoning strategy implemented under `core/reasoning/soft_reasoning` / `soft_exploration`:

- first-generated-token embedding intervention;
- latent perturbation/search;
- verifier-guided objective;
- Gaussian-process Bayesian optimization;
- explicit test-time compute accounting.

Soft Reasoning is a reasoning capability, not a memory-retrieval subsystem.

### Recall primitives

Semantic similarity, lexical retrieval, graph expansion, novelty/retrieval-gap scoring, recency signals, and source-local candidate generation are **recall primitives**. They sit below NeuroRecall and must not be called Soft Reasoning in new architecture documentation or APIs.

### NeuroRecall

NeuroRecall owns authorized memory candidate governance, fusion, ranking, deduplication, guardrails, selection, and recall disposition. It does not own storage, provider execution, final synthesis, prompt assembly, or global policy.

### NeuroVault

NeuroVault owns governed durable memory mutation. Memory formation may create candidates/observations; Runtime and memory policy submit eligible mutations through NeuroVault.

## Reasoning authorization

Reasoning modes are a separate policy domain from generic capabilities.

Canonical flow:

```text
TaskSignature
  -> CORTEX ReasoningEligibilityDecision
  -> requested_reasoning_modes
  -> RuntimePolicy
       -> allowed_reasoning_modes
       -> denied_reasoning_modes + reasons
  -> AuthorizedExecutionPlan
  -> RuntimeReasoningBridge
  -> ReasoningExecutor
```

An empty requested set stays empty. RuntimePolicy and Runtime must not create a default mode.

`soft_exploration` is treated as a specific test-time-scaling protocol. The strict paper-aligned profile currently declares a maximum 30 model-call envelope. RuntimePolicy may deny it because of runtime level, risk, or insufficient model-call budget even when CORTEX considers it cognitively useful.

## Workflow semantics

Complexity is not workflow topology.

CORTEX must model these independently:

- task complexity;
- reasoning depth;
- reasoning mode;
- tool chaining;
- branching;
- checkpoint/resume requirements;
- human approval nodes;
- parallel execution;
- agent delegation.

A difficult conceptual question can require deep reasoning without LangGraph. LangGraph is selected only for real graph/workflow semantics.

## Memory scope contract

Recall and persistence are independent decisions.

Required future contract shape:

```text
MemoryReadDecision
  scope/classes/namespaces/top_k/budget

MemoryWriteDecision
  requested/authorized/classes/retention/policy context
```

`tenant_id`, `user_id`, `session_id`, `conversation_id`, and authorized memory classes/namespaces must be typed fields propagated end-to-end. Do not use dynamic `setattr()` scope propagation in canonical production contracts.

## Composition rule

Stateful canonical services must be built at application/runtime composition boundaries and injected downward. Compatibility getters may temporarily resolve through the composition container, but cognitive/memory subsystems must not silently build alternate registries, recall engines, policy engines, model managers, or persistence authorities.

Target RuntimeComposition includes at least:

- CORTEX;
- RuntimePolicy;
- PromptRuntime;
- MemoryRuntimeManager;
- NeuroRecall source graph;
- MemoryFormation/NeuroVault adapters;
- ReasoningBridge;
- provider/model runtime manager;
- workflow runtime;
- observability emitter;
- trajectory/outcome recorders;
- expression gateway.

## Research guidance

The following recent research is relevant to KAREN's architecture. It guides mechanisms; it does not create new owners.

### Test-Time Scaling in Reasoning LLMs: Inference Regimes, Evaluation, and Reproducibility — arXiv:2608.04001

Key architectural implication: test-time reasoning algorithms are different inference protocols, not one generic scalar `reasoning_depth`. KAREN must record the selected protocol, model-call/token/latency budget, uncertainty, and reproducibility metadata.

### Scaling Test-time Compute for LLM Agents — arXiv:2506.12928

Key implication: more inference compute can help agents, but knowing **when** to reflect/scale is important; list-wise verification and diversified rollouts can outperform naive repeated reasoning. KAREN should learn/select escalation rather than enable expensive reasoning universally.

### Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers — arXiv:2603.07670

Key implication: memory is a governed write-manage-read loop with temporal scope, representation, and control-policy dimensions. This supports KAREN's separation of MemoryFormation/NeuroVault, NeuroRecall, and Runtime/CORTEX control.

### Active Context Compression: Autonomous Memory Management in LLM Agents — arXiv:2601.07190

Key implication: context compression can be an active cost-aware capability. KAREN should treat compression as governed working-context management, not durable-memory truth. The reported study is small, so this is a direction to evaluate rather than an authority to copy blindly.

### Soft Reasoning — Zhu et al., ICML 2025 / arXiv:2505.24688

Key implication: Soft Reasoning is a concrete test-time reasoning/search strategy over internal token embeddings. It belongs under the reasoning capability layer and requires explicit capability/budget gating.

### Memento: Fine-tuning LLM Agents without Fine-tuning LLMs — arXiv:2508.16153

Key implication: learned episodic case selection is a plausible future policy beneath NeuroRecall. It is not part of the current deterministic NeuroRecall authority and must be evaluated against a deterministic baseline before adoption.

## Implementation phases

### Phase A — active now

- [x] Reserve Soft Reasoning for the reasoning strategy in this ADR.
- [x] Add first-class typed reasoning-mode policy helper.
- [x] Fail closed on insufficient strict Soft Reasoning model-call budget.
- [x] Add unit proof for alias normalization, runtime-level restrictions, risk restrictions, and compute budget.
- [ ] Wire reasoning authorization into `RuntimePolicyEnforcer.evaluate()`.
- [ ] Add `requested_reasoning_modes` to `PolicyEvaluationRequest`.
- [ ] Add `allowed_reasoning_modes` / `denied_reasoning_modes` to `PolicyDecision`.

### Phase B — authority relocation

- [ ] Make CORTEX return a policy-free cognitive decision.
- [ ] Runtime invokes RuntimePolicy after CORTEX.
- [ ] RuntimePolicy creates the canonical AuthorizedExecutionPlan.
- [ ] Remove policy construction/execution from `core/cortex/executive.py`.

### Phase C — cognitive-state convergence

- [ ] Make TaskSignature the canonical CORTEX feature input.
- [ ] Move lexical fallback heuristics into Intelligence feature producers.
- [ ] Separate complexity from workflow semantics.
- [ ] Add selector telemetry: requested/allowed/denied modes, expected utility, compute envelope, escalation reason, observed benefit.

### Phase D — memory and composition closure

- [ ] Type `session_id` and authorized namespaces/classes in `MemoryQuery`.
- [ ] Propagate CORTEX recall classes/namespaces into NeuroRecall.
- [ ] Separate memory read/write decisions and execution gates.
- [ ] Replace split recall metadata with one typed RecallExecutionResult.
- [ ] Move memory/retrieval globals into RuntimeComposition.
- [ ] Extract remaining `_memory_runtime_base` compatibility behavior and remove inheritance.
- [ ] Move subsystem counters into canonical observability.

## Proof

Minimum proof for this program:

```bash
python -m compileall src
pytest tests/core/test_runtime_reasoning_policy.py -q
pytest tests/architecture/ -q
pytest tests/cognitive/ -q
pytest tests/memory/ -q
ruff check src tests
mypy src
```

Architecture proof must also assert:

- Runtime never invents a reasoning mode;
- Policy returns an explicit allowed/denied reasoning-mode set;
- CORTEX has no RuntimePolicy instance after Phase B;
- Soft Reasoning is absent from memory/recall authority documentation except migration notes;
- recall scope is preserved through every source adapter;
- durable mutation reaches NeuroVault only.

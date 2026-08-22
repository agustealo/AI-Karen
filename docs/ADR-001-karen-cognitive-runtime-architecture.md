# ADR-001: KAREN Cognitive Runtime Architecture

**Version:** 1.0  
**Date:** 2026-08-22  
**Status:** Proposed  
**Deciders:** Architecture Team  

---

## 1. Context

KAREN is evolving from a chatbot wrapper into a **local-first cognitive runtime** with:

- Understanding, memory, reasoning, tools, plugins, agents, and workflows
- Provider abstraction and policy/security
- Durable execution, observability, and future learning

The current repository contains multiple systems that have grown into competing control planes:

- `KIRERouter` owns task analysis, cognitive reasoning, provider selection, health logic, and fallback
- `EnhancedLLMRouter` defines its own `RoutingPolicy` and `RuntimeLevel`
- `IntelligentModelRouter` carries routing, performance metrics, and fallback options
- `llm_orchestrator.py` owns routing, load balancing, fallback, health, and resource checks
- `AgentMedusa` contains its own `SafetyManager`, `Coordinator`, `Planner`, `Registry`, and `Policy`

This creates "brain competition" where five or more modules believe they are the canonical authority for similar decisions. The architecture must be tightened to eliminate this duplication while preserving modularity, DRY principles, local-first behavior, prompt-first design, and security.

---

## 2. Decision

Adopt a **four-plane centralized authority** architecture for KAREN, where every kind of decision has exactly one canonical owner, and every specialist operates beneath that authority through typed contracts.

Central authority is defined as **contract flow**, not a single monolithic class.

---

## 3. Architecture

### 3.1 Four Planes

```
               KAREN COGNITIVE CONTROL PLANE

                    IntelligenceRuntime
                           │
                           ▼
                        CORTEX
                           │
                 ExecutionRequirements
                           │
                           ▼
                     RuntimePolicy
                           │
                           ▼
                    Runtime Authority
                    /      |       \
                   /       |        \
             DIRECT    WORKFLOW    MULTI-AGENT
                │          │           │
           Reasoning?   LangGraph    Medusa
                │          │           │
                └──────────┴───────────┘
                           │
                    Execution Ports
                           │
         ┌─────────────────┼──────────────────┐
         ▼                 ▼                  ▼
    PromptRuntime      Tool/Plugin        Memory
         │
         ▼
    ProviderRouter
         │
         ▼
   ExpressionGateway
         │
         ▼
       Adapter
```

#### Plane 1: Cognitive Decision Plane

**Owns:** What is this? What does it require? How complex is it? Which capabilities are needed? What execution topology is appropriate?

**Canonical owners:** `IntelligenceRuntime`, `CORTEX`

**They DO NOT execute.**

#### Plane 2: Governance Plane

**Owns:** Is this allowed? Who may do it? Which resources? Which providers? Which tools? Which plugins? Which agents? What approval is needed?

**Canonical owner:** `RuntimePolicy`

This follows NIST zero-trust architecture, which explicitly separates policy decisions from enforcement using a policy decision point (PDP) and policy enforcement point (PEP).

#### Plane 3: Execution Plane

**Owns:** Actually do the thing.

**Canonical owner:** `RuntimeExecutor`

It delegates to executors:
- Direct execution
- `ReasoningRuntime`
- LangGraph
- Medusa
- `PluginExecutionEngine`
- `ToolExecutionEngine`
- `ExpressionGateway`
- `MemoryRuntime`

These are executors, not rulers.

#### Plane 4: Capability Plane

**Contains:** Reasoning engines, agents, tools, plugins, models, providers, retrievers, workflows.

These advertise capabilities. They do not decide whether they should run.

---

### 3.2 Canonical Request Flow

```
API ingress
    │
    │ request + identity + tenant + correlation_id
    ▼
ChatRuntimeControlPlane
    │
    ▼
ContextAssembler
    │
    ▼
IntelligenceRuntime
    │
    │ IntelligenceSignals
    ▼
CORTEX
    │
    │ ExecutionRequirements
    ▼
RuntimePolicy
    │
    │ AuthorizedExecutionPlan
    ▼
RuntimeExecutor
    │
    ├────────────── DIRECT
    │
    ├────────────── REASONING
    │                    ↓
    │             ReasoningRuntime
    │
    ├────────────── WORKFLOW
    │                    ↓
    │               LangGraph
    │
    └────────────── MULTI_AGENT
                         ↓
                       Medusa

All branches
    ↓
PromptRuntime where generation required
    ↓
ProviderRouter
    ↓
ExpressionGateway
    ↓
Provider Adapter

Side-effect boundaries
    ↓
Policy Enforcement Point
    ↓
Tool / Plugin / Memory / External Action
```

---

## 4. Key Contracts

### 4.1 ExecutionRequirements (CORTEX output)

```text
ExecutionRequirements

request_id
correlation_id

intent
intent_confidence

required_capabilities
optional_capabilities

reasoning_required
reasoning_depth
reasoning_modes

memory_read_required
memory_write_candidate

tools_required
plugin_candidates

execution_topology
    DIRECT
    REASONING
    WORKFLOW
    MULTI_AGENT

workflow_id?
agent_topology?

modality
output_contract

latency_class
privacy_class
resource_class

provider_capability_requirements

approval_candidate

risk_signals
```

This is **not authorization**. CORTEX produces it. RuntimePolicy constrains it.

### 4.2 AuthorizedExecutionPlan (RuntimePolicy output)

```text
AuthorizedExecutionPlan

execution_id
policy_decision_id

topology = MULTI_AGENT

allowed_capabilities
allowed_tools
allowed_plugins
allowed_agents

provider_constraints

memory_scope
resource_scope

token_budget
tool_budget
model_call_budget
time_budget

approval_requirements

reasoning_modes

workflow_id
agent_topology

degraded_allowed

audit_context
```

Then nothing below RuntimePolicy needs to re-decide authorization. This is the clean PDP → PEP separation NIST encourages.

### 4.3 ExecutionTopology (canonical enum)

```text
DIRECT
REASONING
WORKFLOW
MULTI_AGENT
```

**DEGRADED is not a topology.** Degraded is state/metadata.

### 4.4 Execution Budgets

```text
ExecutionBudget

max_duration_ms
max_model_calls
max_reasoning_steps
max_tool_calls
max_agent_turns
max_parallelism
max_input_tokens
max_output_tokens
max_memory_items
max_external_requests
```

CORTEX recommends. RuntimePolicy caps. Runtime enforces.

### 4.5 Execution Contexts

Every executor receives a scoped context:

```text
ExecutionContext (base)

request_id
correlation_id
user_id
tenant_id
session_id
conversation_id

policy_decision_id
allowed_capabilities
resource_scope
deadline
budget
audit_context
```

Specialized contexts extend it:
- `ReasoningExecutionContext`
- `WorkflowExecutionContext`
- `AgentExecutionContext`
- `ToolExecutionContext`
- `PluginExecutionContext`
- `ProviderExecutionContext`

No raw giant `dict`.

---

## 5. Retirements and Authority Changes

### 5.1 KIRERouter

**Current role:** Router with task analysis, cognitive reasoning, provider selection, health logic, and fallback.

**New role:** KIRE becomes a CORTEX reasoning/routing **intelligence component** (signal producer).

KIRE produces signals:
- `preferred_capabilities`
- `latency_sensitivity`
- `privacy_requirement`
- `local_preference`
- `reasoning_requirement`
- `model_capability_requirement`

Then:
```
KIRE signals → CORTEX consumes → ProviderRouter selects provider
```

**KIRE must stop being a router.**

Failure ownership moves to `RuntimeResilience`. KIRE must not hide architectural failures by silently choosing another provider.

### 5.2 EnhancedLLMRouter

**Current role:** "Unified Routing System" with its own `RoutingPolicy`, `RuntimeLevel`, and `EnhancedRouteDecision`.

**Decision:** Authority deleted. Unique behavior mined and migrated to canonical owners.

### 5.3 IntelligentModelRouter

**Current role:** Full router with `TaskType`, `RoutingStrategy`, performance metrics, connection states, and fallback options.

**Decision:** Retirement project. Forensic extract unique connection/performance behavior. Move to canonical owners. Delete router authority.

### 5.4 Legacy llm_orchestrator.py

**Current role:** Owns `ModelRegistry`, `ModelInfo`, `SecurityEngine`, `HardwareManager`, `ExecutionPool`, routing, load balancing, fallback, health, resource checks.

**Decision:** Explicit retirement project.

Process:
1. Forensic extract useful behavior (hardware pressure, circuit logic, security utilities, resource monitoring, unique metrics)
2. Move to canonical owners
3. Reference audit for any remaining callers
4. Delete

### 5.5 Agent Medusa

**Current role:** "Canonical AgentMedusa Service" with its own `SafetyManager`, `Coordinator`, `Planner`, `Registry`, `Execution`, `Policy`, and `Arbitration.

**New role:** Multi-agent execution topology coordinator only.

Changes:
- **Remove independent safety authorization.** Medusa must not scan requests using broad regexes.
- **Remove provider routing.** Medusa must not directly import `llm_router_service`.
- **Remove fallback content generation.** Degraded responses must be explicitly marked and produced through canonical degraded-response handling.
- **Replace static fake planner.** Current planner simulates a simple sequential plan with fixed specialists. This is scaffolding, not operational planning.
- **Introduce scoped agent manifests.** Medusa specialists registered with `AgentManifest` containing capabilities, allowed tools/plugins, model requirements, max runtime, and required permissions.

```
Medusa proper flow:

CORTEX
↓
"multi-agent topology required"

RuntimePolicy
↓
"agents analyst + researcher permitted"

RuntimeExecutor
↓
MedusaExecutionRuntime

Medusa
↓
coordinate specialists
```

---

## 6. LangGraph Role

LangGraph is a **workflow execution capability**, not the application architecture.

Use LangGraph where it excels:
- Long-running workflows
- Branching and parallel steps
- Checkpoint/resume
- Human approval and retries
- Multi-stage tool chains
- State machines

Do not use LangGraph for:
- Ordinary chat
- Single inference
- Simple questions
- Simple tool calls
- Every chat request

### Approval Handling

Current custom approval gates should be replaced with LangGraph's checkpoint-backed `interrupt()` / `resume` pattern. Production should use persistent checkpointing, not `MemorySaver`.

---

## 7. Ownership Matrix

| Responsibility              | ONE owner                         |
|-----------------------------|-----------------------------------|
| Signal extraction           | `IntelligenceRuntime`             |
| Intent                      | `CORTEX`                          |
| Execution topology          | `CORTEX`                          |
| Reasoning requirement       | `CORTEX`                          |
| Authorization               | `RuntimePolicy`                   |
| Execution                   | `RuntimeExecutor`                 |
| Prompt assembly             | `PromptRuntime`                   |
| Provider selection          | `ProviderRouter`                  |
| Provider availability       | `ProviderRegistry`                |
| Provider health             | `ProviderHealth`                  |
| Fallback/retry              | `RuntimeResilience`               |
| Specialized reasoning       | `ReasoningRuntime`                |
| Graph workflow              | LangGraph                         |
| Multi-agent coordination    | Medusa                            |
| Plugin execution            | `PluginExecutionEngine`           |
| Tool execution              | `ToolExecutionEngine`             |
| Memory strategy             | NeuroRecall                       |
| Persistence                 | canonical memory runtime          |
| External adapters           | `integrations`                    |
| Audit/tracing               | `Observability`                   |

---

## 8. Hierarchical Planning

Planning is not wrong in multiple places. What is wrong is planning at the **same abstraction level**.

| Level | Owner           | Plans                        |
|-------|-----------------|-------------------------------|
| 1     | `CORTEX`        | Topology (multi-agent, reasoning, workflow) |
| 2     | Workflow planner| Workflow structure (gather, analyze, verify, synthesize) |
| 3     | Specialist      | Local task (search, extract, compare) |

Rule: A lower layer may plan **inside its assigned scope**, but may never expand its own authority.

---

## 9. Decision Provenance

Every decision must carry:

```text
decision_id
decision_type
owner
version
inputs_used
signal_refs
rule_version
confidence
created_at
```

This enables answering "Why did KAREN choose X?" and is required for future reinforcement learning.

---

## 10. Degraded Mode

Collapse multiple degraded/fallback/emergency/safe/reduced concepts into one canonical:

```text
DegradationState

degraded: bool
reason_code
level
original_requirement
actual_execution
capabilities_lost
fallback_level
```

`RuntimeResilience` owns it. Specialists report failure only.

---

## 11. Response Provenance

Every final result must carry:

```text
response_source

MODEL
TOOL
PLUGIN
AGENT
WORKFLOW
CACHED
UNAVAILABLE
```

This eliminates ambiguity and prevents strings like "Processed successfully." from masquerading as AI responses.

---

## 12. Consequences

### Positive

- **Eliminates brain competition.** One canonical owner per responsibility.
- **DRY without monolith.** Centralized contract flow, not giant classes.
- **Local-first.** Resource data feeds CORTEX/ProviderRouter as signals, not as a second router.
- **Security by design.** PDP/PEP separation, scoped execution contexts, policy enforcement at every side-effect boundary.
- **Testable.** Each plane has typed contracts. Deterministic rules, versioned decision rules.
- **Durable execution.** LangGraph used for its strengths (checkpointing, resume, streaming).
- **Learnable.** Canonical execution events and decision provenance enable future trajectory/outcome learning.
- **Maintainable.** Clear retirement path for competing routers and orchestrators.

### Negative

- **Refactoring effort.** Significant migration work to retire KIRE, EnhancedLLMRouter, IntelligentModelRouter, llm_orchestrator, and Medusa's independent authority.
- **Transition complexity.** Existing callers of retired systems need migration paths.
- **Discipline required.** Every new capability must plug into the typed contract system, not invent its own router.

### Neutral

- **LangGraph remains a capability.** It is not the runtime, but a workflow executor plugged into the execution plane.
- **Medusa remains a capability.** It is not a peer to KAREN, but a multi-agent execution topology plugged into the execution plane.

---

## 13. What NOT to Build

Do **not** create:

- `BrainManager`
- `MasterRouter`
- `CentralOrchestrator`
- `SuperRuntime`
- `UniversalRegistry`
- `MegaAgentController`
- `AIKernelManager`

Central authority is the **contract flow**, not a giant class.

---

## 14. Implementation Roadmap

### Block A: Brain Competition Closure

| Sprint             | Goal                                          |
|--------------------|-----------------------------------------------|
| BRAINCLOSE-1       | CORTEX + Intelligence semantic closure        |
| BRAINCLOSE-2       | ReasoningRuntime + KRO dismantling            |
| BRAINCLOSE-3       | LangGraph workflow closure                    |

### Block B: Router and Medusa Retirement

| Sprint             | Goal                                          |
|--------------------|-----------------------------------------------|
| BRAINCLOSE-4       | Medusa multi-agent closure                    |
| BRAINCLOSE-5       | KIRE + model-router extinction                |
| BRAINCLOSE-6       | LLMOrchestrator forensic retirement           |

### Block C: Contracts and Observability

| Sprint             | Goal                                          |
|--------------------|-----------------------------------------------|
| BRAINCLOSE-7       | ExecutionRequirements + AuthorizedExecutionPlan |
| BRAINCLOSE-8       | Execution budgets + scoped contexts + PEPs    |
| BRAINCLOSE-9       | Decision provenance + unified execution events |

### Post-Closure: Learning Foundation

- `ExecutionTrajectory`
- `OutcomeRecord`
- `FeatureRegistry`

---

## 15. References

- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview) - LangGraph as low-level orchestration runtime
- [LangChain Subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents) - Centralized manager/subagent architecture
- [NIST SP 800-207](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf) - Zero Trust Architecture (PDP/PEP)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) - Human-in-the-loop checkpoint patterns
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) - Production checkpointer recommendations
- [LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api) - Idempotent side effects in durable execution
- [OpenAI Guardrails](https://openai.github.io/openai-agents-python/guardrails/) - Input, output, and tool-level guardrails
- [OpenAI Tracing](https://openai.github.io/openai-agents-python/tracing/) - Execution hierarchy tracing

# KARI OS Adversarial Architecture Burn

Date: 2026-09-14
Status: Architecture audit / implementation program

## Objective

Test the live repository against the KARI OS direction: a domain-neutral, local-first cognitive operating substrate that can safely host personal, family, enterprise, creative and other specializations without allowing those domains to seize core authority.

This document is intentionally adversarial. Presence of a package, class or contract is not treated as proof of live behavior.

## Executive verdict

The repository already contains much of the correct substrate: CORTEX, runtime authority, cognitive/context/adaptive areas, layered memory, provider orchestration, governed persistence, Agent Medusa, LangGraph boundaries, RBAC/tenant controls, observability and substantial CI contracts.

The architecture is therefore closer to KARI OS than to the original narrow enterprise-assistant concept.

The principal risk is no longer missing foundations. It is authority fragmentation and premature verticalization while several universal contracts remain incomplete.

### Strong / preserve

- local-first provider architecture
- thin-route/runtime-authority direction
- CORTEX decision versus Runtime execution separation
- RuntimePolicy security dominance
- layered memory with NeuroRecall/NeuroVault ownership
- tenant/RBAC/audit hardening
- Agent Medusa distributed execution controls
- explicit cognitive and release proof workflows
- backend-truth UI direction

### Weak / incomplete

- automation is currently a shallow core contract rather than durable agency
- no sufficiently canonical generic WorldModel contract yet
- craft/practice learning is not a first-class universal subsystem
- event-driven cognition remains too chat-shaped
- extension taxonomy does not yet strongly distinguish connector/domain/skill semantics
- autonomy/delegation is not yet a single first-class policy contract
- current LangGraph convergence work demonstrates remaining alternate-entry authority hazards
- architecture maturity still exceeds exact-head release proof

## Burn 1: Automation is named correctly but behaviorally underbuilt

Observed: `src/ai_karen_engine/core/automation/contracts.py` currently defines generic flow types and input/output contracts. This is a useful seed but not the durable commitment engine required for human-like continuity.

Missing proof:

- durable commitments surviving restart
- trigger registration and deduplication
- event/time wakeups
- context refresh before execution
- RuntimePolicy re-authorization at wake time
- approval lifecycle
- recurrence
- distributed ownership
- outcome evaluation
- follow-up/retry semantics
- cancellation and expiry
- tenant-safe durable persistence

Direction: expand the existing canonical automation domain. Do not create competing scheduler/proactive-agent runtimes.

## Burn 2: Chat remains too structurally important

KARI OS cannot equate cognition with HTTP chat. Chat must become one event source among user messages, schedules, connector events, system events, memory commitments, agent completions and workflow events.

Constraint: generalization must happen inside canonical Runtime contracts. Creating an EventRuntime beside ChatRuntime would reproduce the orchestration split KARI has spent multiple burns removing.

## Burn 3: World knowledge needs universal primitives before Organization Model

The earlier Organization Model proposal is too vertical for core. Department, employee and KPI should be Enterprise Domain Pack semantics.

Core needs a minimal typed WorldModel vocabulary: entity, person, group, role, relationship, artifact, process, resource, rule, goal, commitment, dependency, event, context and outcome.

Adversarial test: if Family, Personal and Enterprise cannot share the same core graph/contracts without branching core logic by domain, the model is not universal enough.

## Burn 4: Institutional Craft is valuable but incorrectly scoped as core

Brand preservation is an excellent reference workload, but Brand is not a universal cognitive primitive.

Core should own Craft & Practice semantics: artifact, exemplar, technique, critique, constraint, rationale, accepted/rejected outcome, exception and evolution. An Institutional Craft/Brand pack specializes those primitives.

This prevents a valuable enterprise use case from narrowing the operating substrate.

## Burn 5: Extensions need stronger constitutional boundaries

A plugin architecture alone is insufficient. Extensions must be classified because their authority differs.

- Connector: capability/event bridge to an external system.
- Domain Pack: specialized ontology/policy/workflow semantics.
- Skill Pack: reusable expert practice.

No extension may own authentication, tenant resolution, provider routing, memory persistence authority, CORTEX decisions, RuntimePolicy, or canonical execution.

Every extension requires explicit capabilities, permissions, schemas, provenance, audit and tests.

## Burn 6: Autonomy must become explicit policy

Tool availability must never imply permission to act. KARI needs one autonomy/delegation contract that composes with RuntimePolicy and supports observe, recommend, prepare, approve-then-execute, delegated execution and managed execution.

A domain pack can describe desired behavior but cannot elevate its own autonomy.

## Burn 7: LangGraph remains a live authority-convergence warning

The current open CORTEX/LangGraph authority work shows why this manifest is necessary. Validation-only graph auth is directionally correct, but direct agent execution paths must not create or accept client-controlled identity context as a substitute for Runtime-derived authority.

Required end state: every production LangGraph invocation receives server-derived identity/tenant/policy context through canonical Runtime/WorkflowRuntime authority. Direct API entry points may normalize and delegate, not establish a second graph execution authority.

## Burn 8: Agent Medusa must remain execution infrastructure

Medusa's distributed ownership, fencing, cancellation and durable run controls are valuable OS execution capabilities. They must not evolve into a second cognitive planner, policy authority or memory authority.

CORTEX/Runtime decides what work exists. RuntimePolicy decides whether it is permitted. Medusa governs distributed execution of authorized work.

## Burn 9: Memory sophistication must be judged longitudinally

The repository has advanced memory concepts, but package presence does not prove human-like continuity.

Required behavioral benchmarks:

- revise a previously believed fact when stronger evidence arrives
- retain an unresolved commitment across restart
- forget/decay information under configured retention policy
- prevent cross-tenant recall
- distinguish observation from inference
- preserve evidence/provenance
- detect preference drift without overwriting contradictory evidence
- recall relationship context appropriately
- preserve a learned practice and explain why it is preferred

## Burn 10: Exact-head proof remains part of architecture truth

KARI's methodology rejects green-by-assumption. A strong workflow definition is not a passing build. Release claims require the canonical gates to run against the immutable release SHA and produce an attributable verdict.

No developer manifest may equate mergeable, compiled locally, or historically green with release-ready.

## Implementation program

### KARI-OS-1: Authority convergence

Finish the CORTEX -> RuntimePolicy -> Runtime -> WorkflowRuntime -> LangGraph identity/execution chain. Remove or quarantine direct alternate execution authorities.

### KARI-OS-2: Architecture contract tests

Add tests that reject domain-specific core leakage, direct connector/plugin execution, client-controlled tenant/auth context, and alternate memory/provider/runtime authorities.

### KARI-OS-3: Universal WorldModel contracts

Introduce minimal typed domain-neutral primitives. Reuse existing cognitive/evidence/temporal contracts rather than duplicating them.

### KARI-OS-4: Durable Commitment Runtime

Expand `core/automation` around commitments, triggers, wakeups, approvals, recurrence, outcomes and recovery. Reuse Runtime, RuntimePolicy, Medusa, existing stores and telemetry.

### KARI-OS-5: Craft & Practice model

Add generic practice-learning contracts and formation/retrieval paths. Prove with at least creative, personal and enterprise examples.

### KARI-OS-6: Governed extension taxonomy

Extend plugin manifests to declare connector/domain-pack/skill-pack class, capabilities, permissions, prompts, schemas, data ownership and policy requirements.

### KARI-OS-7: Generality benchmark

Run the same core through Personal, Family and Enterprise reference configurations. Domain behavior belongs in manifests/packs; core forks fail the benchmark.

### KARI-OS-8: Longitudinal cognition benchmark

Test continuity across time, contradiction, goals, commitments, relationships, learned practice and provenance, including restart and multi-tenant isolation.

## Developer stop conditions

Stop and perform an architecture audit before merging when a change:

- adds a new runtime/orchestrator/provider registry/memory store authority;
- puts a vertical noun into core contracts;
- allows a plugin/connector/domain pack to execute without RuntimePolicy;
- accepts tenant/user/role authority from client-controlled payloads;
- writes memory outside canonical formation/NeuroVault paths;
- adds a second scheduler or proactive engine instead of extending core automation;
- lets UI infer backend capability or persistence truth;
- uses LangGraph for simple chat or as an alternate runtime;
- makes Medusa decide cognitive intent;
- introduces prompts without versioned prompt contracts and tests;
- claims a release without exact-SHA proof.

## Proof commands

At minimum for implementation slices:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
npm run lint && npm run typecheck && npm test && npm run build
docker compose config
```

Use narrower tests during development, but architecture-affecting merges require the applicable canonical gates.

## Final judgment

Do not rewrite KARI. Converge it.

The current repository has the machinery for a credible cognitive OS, but it will become a collection of impressive subsystems if universal contracts, runtime authority and extension boundaries are not frozen now. The next architectural gains should come from integration and behavioral proof, not additional parallel foundations.

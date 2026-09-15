# KARI OS Architecture Manifest

Status: Canonical architecture direction

## Mission

KARI is a local-first, prompt-first, domain-neutral cognitive operating substrate. It provides governed continuity across identity, memory, relationships, context, goals, commitments, reasoning, policy, actions, outcomes, and adaptation. Enterprise, personal, family, creative, research, education, and industry-specific behavior are specializations of the substrate, not alternate KARI cores.

KARI must remain capable of safely hosting partner systems without surrendering runtime authority.

## Non-negotiable architecture law

**Core stores universal cognitive primitives. Domain packs provide semantics. Skill packs provide reusable practice. Connectors provide external capabilities. Runtime retains authority.**

One responsibility -> one owner -> one registry -> one config -> one runtime path.

No extension, API route, UI surface, workflow engine, agent system, or provider may become an alternate cognitive/runtime authority.

## What belongs in KARI OS

A capability belongs in core when it is domain-neutral, broadly reusable, fundamental to cognitive continuity, or defines authority that extensions must not reinvent.

### Platform kernel

- identity, authentication, tenant isolation
- RBAC, policy enforcement, audit
- configuration and secrets
- provider/model registry and local-first routing
- storage and distributed coordination
- observability, correlation, resource/execution budgets
- extension lifecycle and capability governance

### Cognitive runtime

- event/request normalization
- context assembly
- CORTEX decisions
- RuntimePolicy authorization
- reasoning selection
- execution planning and delegation
- outcome evaluation
- persistence and telemetry

Chat is an interaction modality, not the definition of cognition. Long-term runtime contracts must support user, system, scheduled, connector, workflow, memory, and agent events without creating parallel runtimes.

### Cognitive continuity

- STM, episodic and durable memory
- NeuroRecall and NeuroVault
- temporal and prospective memory
- reflection, consolidation, forgetting/revision
- SelfModel and PersonModel
- RelationshipModel
- generic WorldModel
- evidence, provenance, confidence and contradiction

### Universal world primitives

Core may define generic concepts such as:

- Entity
- Person
- Group
- Role and RoleAssignment
- Relationship
- Artifact
- Process
- Resource
- Rule
- Goal
- Commitment
- Event
- Context
- Dependency
- Outcome

Core must not hard-code Department, CRM Opportunity, Family Household Rule, Jira Issue, Salesforce Lead, or other vertical concepts as universal cognitive primitives.

### Agency

KARI core owns the semantics of goals, commitments, triggers, wakeups, approval requirements, autonomy boundaries, outcomes and follow-up. Execution remains runtime-owned.

Canonical proactive cycle:

Observation -> Interpretation -> Goal/Commitment candidate -> persistence decision -> trigger registration -> wake event -> context refresh -> CORTEX decision -> RuntimePolicy -> execution plan -> approval gate when required -> execution -> outcome evaluation -> memory formation -> goal/commitment update.

A scheduled trigger never authorizes stale execution by itself. Context and policy must be re-evaluated at wake time.

### Craft and practice

KARI may learn generic ways of doing things through artifacts, exemplars, techniques, critiques, constraints, decisions, rationale, accepted/rejected outcomes, exceptions and evolution over time. Brand preservation is a domain specialization of this generic Craft & Practice model, not a hard-coded enterprise core.

## What does not belong in KARI OS core

Examples include Salesforce, Jira, Slack, accounting workflows, healthcare schemas, brand templates, family rules, household routines, CRM vocabulary, school curricula, smart-home integrations, legal workflows and tool-specific creative behavior.

These belong in governed extensions unless a genuinely domain-neutral primitive is first proven necessary.

## Extension taxonomy

### Connector

Connects KARI to an external system or modality. A connector supplies capabilities and events, not cognition or authorization. Examples: email, calendar, GitHub, Slack, filesystem, Home Assistant, CRM.

### Domain Pack

Supplies specialized ontology, schemas, prompts, policies, reasoning hints, evaluation rules and workflows using core primitives. Examples: Enterprise, Personal, Family, Creative Studio, Research, Education.

### Skill Pack

Supplies reusable expert practice that can cross domains. Examples: design, coding, research, writing, project management.

All extensions require manifests, typed input/output contracts, permissions, RBAC/policy integration, tenant scope, provenance, audit, telemetry, versioning and tests.

## Autonomy contract

Autonomy is explicit policy, never an emergent side effect of tool access.

Recommended semantic levels:

- A0 Observe: detect/report only.
- A1 Recommend: propose an action.
- A2 Prepare: prepare an artifact/action without committing it.
- A3 Approve then execute: explicit approval is required.
- A4 Delegated execution: execute inside pre-authorized scope.
- A5 Managed execution: execute, monitor outcomes and escalate exceptions inside delegated scope.

Domain packs may request an autonomy level but cannot grant it. RuntimePolicy and deployment governance remain authoritative.

## Runtime governance profile

Every deployment must be able to answer, in machine-readable policy:

- Who/what is KARI serving?
- What may KARI observe?
- What may KARI remember and for how long?
- What may KARI infer?
- What may KARI execute?
- What requires approval or confirmation?
- What may never be delegated?
- Who may modify these rules?

This profile must compose with tenant, user, role, domain-pack, connector and action policies without bypassing higher-priority restrictions.

## Ownership boundaries

- API routes are thin ingress only.
- CORTEX decides; it does not execute.
- RuntimePolicy authorizes.
- Runtime executes and persists.
- LangGraph is used only for true graph workflows and remains subordinate to Runtime.
- Agent Medusa is a specialist execution subsystem and may not become a second runtime authority.
- Memory stores do not decide policy.
- NeuroRecall retrieves; it does not become another store.
- NeuroVault governs persistence; no direct side-door memory writes.
- UI displays backend truth and never invents availability, routing, persistence or fallback state.
- Connectors expose capabilities/events; they never own user identity, tenant identity, cognitive state, provider routing, or authorization.

## Naming and methodology guardrail

Use domain-neutral names in core. If a proposed core type contains a vertical noun such as employee, department, CRM, family, brand, Jira, Salesforce, classroom, patient, or campaign, first prove why it cannot be represented by universal primitives plus a pack.

Do not rename established authorities casually. CORTEX, NeuroRecall, NeuroVault, Agent Medusa, RuntimePolicy and canonical Runtime names retain their project meanings unless an explicit migration plan updates code, contracts, tests, documentation and telemetry together.

## Required architecture proof

Any change affecting these boundaries must prove:

1. no duplicate authority was introduced;
2. tenant and identity scope remain explicit;
3. RBAC/policy dominates extension or agent intent;
4. prompts remain explicit/versioned/testable where reasoning is introduced;
5. local-first provider behavior is preserved;
6. persistence uses canonical memory/runtime paths;
7. observability includes correlation and actual execution provenance;
8. compatibility shims have an owner and sunset when retained;
9. direct API/UI/connector execution cannot bypass Runtime;
10. domain-specific concepts did not leak into core without an architecture contract.

## Reference configurations

Generality should be proven with at least three deliberately different configurations:

- KARI Personal
- KARI Family
- KARI Enterprise

A domain pack requiring edits to cognitive core is an architecture warning. New core primitives require evidence that they are genuinely universal.

## Design north star

KARI models human-like continuity without claiming consciousness. The target is a system that can remember, revise, relate, maintain unfinished intentions, learn practice, re-evaluate context, coordinate specialists, operate within delegated authority, and explain the evidence and policy behind its actions.

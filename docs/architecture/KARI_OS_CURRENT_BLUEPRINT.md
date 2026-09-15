# KARI OS Current Architecture Blueprint

> **Status:** Canonical current-state + target-state architecture blueprint  
> **Live repository baseline:** `agustealo/AI-Karen@d80d79af63b017162713334dd53fdc3956a9bbc4`  
> **Audit date:** 2026-09-14  
> **Companion documents:** `PROJECT_DEV_MANIFEST.md`, `docs/architecture/KARI_OS_MANIFEST.md`, `docs/architecture/KARI_OS_ADVERSARIAL_BURN.md`  
> **Rule:** Live code, migrations, deployment composition, dependency manifests and executable tests outrank historical diagrams and plans.

# Executive direction

KARI should remain the substrate, not become the vertical.

The correct product direction is a **domain-neutral, local-first cognitive operating substrate** that can maintain governed continuity across identity, memory, relationships, context, goals, commitments, reasoning, action, outcomes and adaptation.

Enterprise, Personal, Family, Creative, Research, Education and other domains should specialize the same cognitive substrate through governed packs and connectors. They should not fork KARI into separate brains.

The architectural law is:

> **Core stores universal cognitive primitives. Domain Packs provide semantics. Skill Packs provide reusable practice. Connectors provide external capabilities. Runtime retains authority.**

This is now aligned with the live repository rather than an aspirational multi-database design.

---

# 1. What KARI is

KARI is not primarily:

- an enterprise assistant;
- a chatbot;
- an agent framework;
- a workflow engine;
- a memory database;
- a provider router;
- a graph database application.

Those are capabilities or deployment shapes.

KARI is the cognitive substrate that coordinates them.

A concise definition:

> **KARI is a local-first cognitive operating system that maintains governed continuity across people, identity, memory, relationships, goals, commitments, environments and actions while allowing domain-specific capabilities to be installed without changing the cognitive core.**

The central design word is **continuity**.

Human-like behavior in KARI means continuity across time, not a claim of consciousness.

KARI should be able to:

- remember;
- revise what it believed;
- distinguish observation from inference;
- preserve unresolved intentions;
- maintain relationship context;
- adapt to preferences;
- learn ways of doing things;
- wake on future commitments;
- refresh context before acting;
- operate within delegated authority;
- explain evidence, policy and actual execution provenance.

---

# 2. Current live repository truth

The live repository is already much closer to this cognitive-OS model than the original enterprise-oriented concept.

## 2.1 Current main

Current audited main:

```text
d80d79af63b017162713334dd53fdc3956a9bbc4
fix(chat): audit and repair chat response journey, schema alignment, and backend tests
```

Two architecture PRs remain open at this baseline:

- **PR #57** — CORTEX/LangGraph identity authority convergence.
- **PR #58** — KARI OS architecture, methodology and stack-truth freeze.

Do not describe #57 or #58 as merged until the repository actually reports them merged.

## 2.2 Current canonical data spine

The current durable data architecture is:

```text
PostgreSQL 15 / Supabase-local deployment
        |
        +-- relational durable state
        +-- JSONB evidence/metadata
        +-- pgvector embeddings
        +-- HNSW semantic index
        +-- PostgreSQL FTS / GIN
        +-- memory entities
        +-- temporal relationships
        +-- RLS / tenant isolation
        +-- transactional lifecycle state
        +-- rebuildable graph projections
```

This replaces the historical idea that canonical memory needed several external databases.

### Active

- PostgreSQL 15
- Supabase-local migration/deployment baseline
- pgvector
- PostgreSQL HNSW vector indexing
- PostgreSQL full-text search
- PostgreSQL JSONB
- PostgreSQL temporal/entity/relation projections
- PostgreSQL RLS
- SQLAlchemy
- asyncpg
- psycopg / psycopg2 where configured

### Retired from canonical memory authority

- Neo4j
- Milvus
- Elasticsearch memory projections
- Kuzu
- DuckDB
- hnswlib

The memory convergence migration explicitly retires Milvus/Elasticsearch projections for canonical memory in favor of PostgreSQL + pgvector + FTS.

The temporal graph migration explicitly states that PostgreSQL/Supabase remains durable authority and graph rows are rebuildable projections.

**Neo4j is not part of the current KARI production stack.**

A future graph accelerator may be approved only through benchmark-backed architecture review and should remain derived/rebuildable unless a deliberate migration changes durable authority.

## 2.3 Current graph direction

KARI already has graph-shaped memory without requiring a graph database product.

Current projection model includes concepts such as:

```text
memory_entity
memory_relation
tenant_id
user_id
source_id
target_id
relation_type
valid_from
valid_to
observed_at
recorded_at
confidence
weight
salience
lifecycle_state
source_memory_id
source_event_id
schema_version
```

Therefore:

> **WorldModel is an ontology and cognitive contract, not a database choice.**

The first WorldModel implementation should reuse the existing PostgreSQL temporal/entity/relation substrate before adding any new datastore.

## 2.4 Redis

Redis 7 remains active for bounded/hot state and distributed coordination.

Current responsibilities include:

- STM/session-adjacent bounded state;
- hot context;
- rate limiting where configured;
- distributed coordination;
- Medusa ownership/cancellation coordination.

Redis is not durable LTM authority.

Do not create a second Redis connection authority.

## 2.5 Backend runtime stack

Current backend estate includes:

- Python;
- FastAPI;
- Uvicorn;
- uvloop;
- httptools;
- Pydantic;
- pydantic-settings;
- SQLAlchemy;
- Alembic / Supabase migrations;
- asyncpg / psycopg;
- Redis client;
- HTTPX / aiohttp where appropriate.

API routes remain thin ingress.

Framework availability does not grant architecture authority.

## 2.6 Local/model inference estate

Current repository/deployment support includes:

- Transformers;
- sentence-transformers;
- Hugging Face assets;
- Ollama as optional local inference;
- vLLM as optional OpenAI-compatible local inference;
- GPU vLLM profile;
- CPU vLLM profile;
- local GGUF server profile;
- OpenAI-compatible clients;
- OpenAI SDK;
- Google Generative AI integration where configured.

A Docker service existing does not make it the selected provider.

Provider/model eligibility belongs to canonical runtime registry/config/health truth.

## 2.7 Workflow and multi-agent estate

Current specialist execution systems include:

- **LangGraph** for true graph workflow semantics;
- **Agent Medusa** for governed multi-agent/distributed execution.

Neither is the global KARI runtime.

The authority chain remains:

```text
CORTEX
   |
   v
RuntimePolicy
   |
   v
Runtime / WorkflowRuntime
   |
   +-- Model Runtime
   +-- Reasoning
   +-- LangGraph when real graph semantics are required
   +-- Agent Medusa when specialist multi-agent execution is required
   +-- governed tools/extensions
```

## 2.8 Observability estate

Current observability includes or supports:

- structured logging;
- python-json-logger;
- Prometheus client;
- Prometheus service profile;
- Grafana service profile;
- OpenTelemetry API/SDK;
- structured audit/lifecycle events;
- request/correlation identifiers.

Architecture truth must be observable from actual execution metadata.

## 2.9 Identity and security

KARI application services remain the identity/security authority.

The local Supabase configuration uses the Supabase data platform while Supabase Auth is disabled.

Current architecture includes:

- canonical AuthService;
- session/token lifecycle;
- backend RBAC;
- tenant scope;
- audit;
- password hashing;
- TOTP capability;
- rate limiting;
- cryptographic utilities;
- PostgreSQL RLS;
- secret-safe configuration.

Client, connector, workflow or graph payloads may not invent user, tenant or role authority.

---

# 3. KARI OS north star

Different domains should reduce to universal cognitive structures.

## Enterprise

```text
Department
Employee
Manager
Project
Policy
Budget
Approval
```

## Family

```text
Household
Parent
Child
Responsibility
Routine
Boundary
```

## Personal

```text
Self
Goal
Habit
Project
Commitment
Preference
```

## Relationship

```text
Person
Partner
Shared commitment
Boundary
History
Expectation
```

## Creative

```text
Artist
Artifact
Style
Critique
Technique
Portfolio
Practice
```

## Research

```text
Researcher
Evidence
Hypothesis
Experiment
Finding
Source
Claim
```

These reduce to domain-neutral primitives:

```text
Entity
Person
Group
Relationship
Role
RoleAssignment
Goal
Commitment
Artifact
Event
Evidence
Rule
Preference
Process
Resource
Decision
Outcome
Context
Dependency
Practice
```

Those belong in KARI OS.

"Sales department", "marriage", "design studio", "classroom", "hospital" and "Salesforce opportunity" do not.

---

# 4. Core versus extension rule

A capability belongs in KARI OS Core when most of the following are true:

1. it is useful across multiple domains;
2. cognition fundamentally depends on it;
3. every specialization may need it;
4. it defines semantics or authority extensions must not reinvent;
5. plugin ownership would fragment identity, memory, policy, reasoning or execution.

A capability belongs in an extension when:

- it is external-system-specific;
- it is domain-specific;
- it introduces specialized vocabulary;
- it can be absent without breaking core cognition;
- it can be represented using core primitives.

Examples:

```text
KARI understands Commitment.
Calendar Connector understands Google Calendar.

KARI understands Relationship.
Family Domain Pack understands guardian / child.

KARI understands Artifact + Practice.
Brand Craft Skill understands typography and campaign constraints.

KARI understands Role + Authority.
Enterprise Domain Pack understands CFO and manager roles.
```

---

# 5. Current-to-target system rings

The strongest conceptual model is seven rings.

```text
+------------------------------------------------------+
|               DOMAIN APPLICATION PACKS               |
| Enterprise | Personal | Family | Creative | Research |
+------------------------------------------------------+
|               CAPABILITY EXTENSIONS                  |
| Email | Calendar | GitHub | CRM | Home | Filesystem  |
+------------------------------------------------------+
|                AUTOMATION / AGENCY                   |
| Goals | Commitments | Triggers | Wakeups | Approvals |
+------------------------------------------------------+
|                 COGNITIVE MODEL                      |
| Self | Person | Relationship | World | Practice      |
+------------------------------------------------------+
|                  MEMORY SYSTEM                       |
| STM | Episodic | Semantic | Temporal | Prospective  |
+------------------------------------------------------+
|                CORTEX + RUNTIME                      |
| perceive | decide | authorize | execute | learn      |
+------------------------------------------------------+
|                 PLATFORM KERNEL                      |
| Auth | Tenant | RBAC | Config | Providers | Audit    |
+------------------------------------------------------+
```

Current maturity is uneven.

- Platform Kernel: strong.
- CORTEX + Runtime: strong but still converging around graph/workflow authority.
- Memory System: substantial and increasingly unified.
- Cognitive Model: partial.
- Automation / Agency: underbuilt.
- Extension taxonomy: partial.
- Domain/Application Packs: target architecture, not yet a complete governed ecosystem.

---

# 6. Platform Kernel: core

The kernel owns:

- identity/authentication;
- tenant isolation;
- RBAC;
- audit;
- policy enforcement;
- configuration;
- provider/model registry;
- secrets;
- observability;
- storage infrastructure;
- extension lifecycle;
- execution budgets;
- distributed coordination.

Domain packs may consume these capabilities.

They may not replace them.

Examples of forbidden drift:

- Enterprise Pack invents a second user store.
- Family Pack invents a second permission system.
- Connector writes durable memory directly.
- Healthcare Pack bypasses RuntimePolicy.
- Graph workflow accepts client-controlled tenant identity.
- UI infers provider availability.

---

# 7. Cognitive Runtime: current and target

## 7.1 Current authority

Current live chat execution is centered on:

```text
Transport / API
      |
      v
ChatRuntime.execute / execute_stream
      |
      v
RuntimeDecisionPipeline
      |
      +--> CortexExecutionDecider
      |
      +--> RuntimePolicyEnforcer
      |
      v
AuthorizedExecutionPlan
      |
      +--> governed memory recall
      +--> direct model execution
      +--> reasoning
      +--> WorkflowRuntime
      +--> LangGraph / Medusa when eligible
      +--> persistence / trajectory / telemetry
```

This is directionally correct.

## 7.2 Current authority gap

PR #57 exists because LangGraph still has an authority convergence issue around runtime-derived auth/tenant context.

The intended end state is:

```text
API / Event ingress
      |
      v
Runtime derives trusted identity/context
      |
      v
CORTEX decides
      |
      v
RuntimePolicy authorizes
      |
      v
WorkflowRuntime adapts authorized work
      |
      v
LangGraph consumes trusted context
```

LangGraph must never:

- authenticate independently;
- synthesize a tenant;
- synthesize a user;
- self-authorize;
- choose providers independently;
- become a parallel memory authority.

## 7.3 Target generalization

The long-term runtime should become event-capable without creating a second EventRuntime.

Conceptually:

```text
Event
  |
  v
Perception / interpretation
  |
  v
CognitiveState
  |
  v
CORTEX
  |
  v
RuntimePolicy
  |
  v
ExecutionPlan
  |
  +--> Respond
  +--> Reason
  +--> Tool
  +--> Workflow
  +--> Multi-agent
  |
  v
Outcome
  |
  v
Formation / reflection / adaptation
```

Chat becomes one event type.

Possible future event sources include:

- user message;
- schedule;
- commitment wakeup;
- connector webhook;
- email;
- file change;
- agent completion;
- device/system event;
- workflow continuation;
- memory-derived prospective trigger.

Generalization must extend canonical Runtime contracts rather than create a new global orchestrator.

---

# 8. Memory: current live design

KARI's live memory direction is now more unified than the older design.

```text
Redis
  |
  +--> bounded STM / hot context

PostgreSQL/Supabase
  |
  +--> memory_event
  +--> memory_assertion
  +--> memory_episode
  +--> profile_fact
  +--> memory_items
  +--> memory_entity
  +--> memory_relation
  +--> reinforcement_event
  +--> contradiction_event
  +--> consent_scope
  +--> retention_policy
  +--> projection_status
  +--> pgvector
  +--> FTS
  +--> temporal graph projections
```

Cognitive memory authority remains layered:

```text
NeuroRecall
  -> retrieval strategy/scoring

MemoryFormation
  -> formation eligibility after actual outcomes

NeuroVault
  -> governed durable mutation/lifecycle
```

## 8.1 Raw experience

What happened?

```text
Event
Interaction
Artifact
Action
Outcome
Observation
```

## 8.2 Knowledge

What does KARI currently hold as knowledge or belief?

```text
Assertion
Claim
Fact
Belief
Preference
Rule
Pattern
Relationship
Skill
Practice
```

## 8.3 Continuity

What remains active over time?

```text
Goal
Commitment
Unresolved thread
Relationship state
Identity
Project
Expectation
Future intention
```

This three-layer cognitive framing should be implemented over the current memory spine rather than introducing new stores.

---

# 9. Universal World Model

The earlier Organization Model concept is too vertical for core.

The replacement is a **Universal WorldModel**.

## 9.1 Core vocabulary

```text
World
+-- Entities
+-- People
+-- Groups
+-- Roles
+-- RoleAssignments
+-- Relationships
+-- Places
+-- Systems
+-- Resources
+-- Artifacts
+-- Processes
+-- Projects
+-- Goals
+-- Commitments
+-- Rules
+-- Dependencies
+-- Events
+-- Contexts
+-- Outcomes
```

## 9.2 Current storage direction

WorldModel should initially map onto the existing PostgreSQL entity/relation/temporal projection infrastructure.

Do not introduce Neo4j merely because the model is relational.

## 9.3 Domain mapping

### Enterprise

```text
Group       -> Department
Role        -> CFO
Process     -> Invoice approval
Rule        -> Procurement policy
Artifact    -> Contract
Resource    -> Budget
```

### Family

```text
Group       -> Household
Role        -> Parent
Process     -> School pickup
Rule        -> Bedtime rule
Artifact    -> School form
Resource    -> Family car
```

### Creative

```text
Group       -> Studio
Role        -> Designer
Process     -> Review cycle
Rule        -> Visual constraint
Artifact    -> Design
Resource    -> Asset library
```

Same cognitive substrate.

Different semantics.

---

# 10. Craft & Practice Model

The earlier Institutional Craft concept was valuable but too enterprise-specific.

Core should instead support **Craft & Practice**.

```text
Practice
+-- artifacts
+-- exemplars
+-- techniques
+-- preferences
+-- decisions
+-- critiques
+-- constraints
+-- accepted outcomes
+-- rejected outcomes
+-- rationale
+-- exceptions
+-- evolution
```

## Graphic design

```text
Practice: visual design
Artifact: campaign layout
Technique: asymmetric grid
Critique: logo too dominant
Exemplar: approved campaign
```

## Carpentry

```text
Practice: cabinetry
Artifact: drawer joint
Technique: dovetail
Critique: tolerance too loose
Constraint: wood movement
```

## Parenting

```text
Practice: helping child study
Technique: short verbal quizzes
Outcome: better retention
Exception: math works better visually
```

## Software engineering

```text
Practice: architecture
Technique: repository pattern
Rejected outcome: duplicate services
Rationale: one source of truth
```

## Relationship

```text
Practice: conflict resolution
Preference: cool-down period
Successful approach: private discussion
Rejected approach: text argument
```

This belongs in KARI because humans maintain not only facts but learned ways of doing things.

Implementation remains target work.

---

# 11. Goals, commitments and durable agency

This remains the most important behavioral gap between the current repo and the OS target.

The desired cycle is:

```text
Observation
   |
   v
Interpretation
   |
   v
Goal / Commitment candidate
   |
   v
Persistence decision
   |
   v
Trigger registration
   |
   v
Wake event
   |
   v
Context refresh
   |
   v
CORTEX decision
   |
   v
RuntimePolicy
   |
   v
Execution plan
   |
   v
Approval gate if required
   |
   v
Execution
   |
   v
Outcome evaluation
   |
   v
Memory formation
   |
   v
Goal / Commitment update
```

The critical rule is:

> **A trigger wakes cognition. It does not authorize stale action.**

Example:

```text
Commitment:
"Buy airline tickets Friday."
```

At wake time KARI must reassess:

- trip still active?
- tickets already purchased?
- destination unchanged?
- price inside user policy?
- approval still valid?
- identity/tenant/tool permissions still valid?
- external capability healthy?

This is the difference between durable cognition and cron with model text attached.

---

# 12. Current automation reality

Current `core/automation` is correctly located but shallow.

The live package currently provides typed automation/flow contracts rather than a complete durable agency subsystem.

Current conceptual ownership should be preserved and expanded.

Target shape:

```text
core/automation/
+-- contracts.py
+-- commitments/
+-- triggers/
+-- scheduler/
+-- wakeups/
+-- approvals/
+-- recurrence/
+-- execution/
+-- outcomes/
+-- recovery/
+-- telemetry/
```

This is conceptual organization, not permission to add directories before auditing existing stronger implementations.

The ownership rule:

```text
Automation:
"This commitment became actionable."

Runtime:
"Given current context and policy, here is whether/how it executes."
```

Forbidden alternatives:

```text
proactive_ai.py
scheduler_v2.py
background_agent.py
task_runtime.py
automation_engine_new.py
```

unless an architecture audit proves no existing canonical owner can absorb the responsibility.

---

# 13. Person Model

KARI should understand people generically.

Not EmployeeModel as core.

Target:

```text
PersonModel
+-- identity
+-- preferences
+-- goals
+-- behaviors
+-- habits
+-- expertise
+-- roles
+-- relationships
+-- commitments
+-- boundaries
+-- interaction style
+-- evidence/confidence
```

The current `core/personalization` area is the natural existing foundation.

Domain packs can specialize:

```text
Enterprise -> Employee
Family     -> Family member
Education  -> Student
Personal   -> Owner/user
Project    -> Contributor
```

---

# 14. Relationship Model

Relationship semantics belong in core.

Not just:

```text
KARI <-> User
```

but:

```text
Entity <-> Entity
```

Examples:

```text
Person  --manages-->       Person
Person  --married_to-->    Person
Person  --owns-->          Device
Person  --works_on-->      Project
Project --depends_on-->    Project
Artifact--created_by-->    Person
Policy  --governs-->       Process
Goal    --shared_with-->   Person
```

The current PostgreSQL relation projection gives KARI a viable storage substrate for this work.

The ontology belongs in KARI contracts.

Storage is implementation detail.

---

# 15. Roles and delegation

Core should understand:

```text
Role
RoleAssignment
Authority
Responsibility
Scope
Delegation
```

Domain packs define names.

## Enterprise

```text
CEO
Designer
HR Manager
Reviewer
```

## Family

```text
Parent
Guardian
Child
Caregiver
```

## Project

```text
Owner
Reviewer
Contributor
Observer
```

A role does not automatically imply RuntimePolicy authorization.

Role is evidence/input to policy.

---

# 16. Policies

Policy mechanism is core.

Policy corpus is modular.

Core semantics may include:

```text
ALLOW
DENY
REQUIRE_APPROVAL
REQUIRE_CONFIRMATION
REQUIRE_CAPABILITY
REQUIRE_ROLE
LIMIT_SCOPE
```

Examples:

### Enterprise

```text
Purchases > $10,000 require CFO approval.
```

### Personal

```text
Never send email without confirmation.
```

### Family

```text
Child role cannot make purchases.
```

Domain Packs may contribute policy rules.

They may not bypass higher-priority RuntimePolicy or deployment governance.

---

# 17. Extension taxonomy

KARI should distinguish three extension classes.

## 17.1 Connector

Connects KARI to an external system or modality.

Examples:

```text
Google Calendar
Gmail
Slack
GitHub
Home Assistant
Salesforce
Filesystem
Camera
Microphone
```

A Connector provides:

- capabilities;
- typed inputs/outputs;
- events;
- external resource handles.

It does not provide independent cognition or authorization.

## 17.2 Domain Pack

Teaches specialized semantics.

Examples:

```text
Enterprise
Family
Personal Productivity
Software Engineering
Creative Studio
Research
Education
Legal
Healthcare
Finance
```

A Domain Pack may contain:

- ontology;
- schemas;
- prompt contracts;
- domain policies;
- reasoning hints;
- workflows;
- evaluation rules.

It cannot replace CORTEX, Runtime, RuntimePolicy or memory authority.

## 17.3 Skill Pack

Adds reusable expert practice.

Examples:

```text
Graphic Design
Writing
Project Management
Budget Analysis
Python Development
Marketing
Meal Planning
Photography
```

Skill Packs should be portable across domains.

---

# 18. Example configurations

## Personal KARI

```text
KARI OS
+ Personal Domain Pack
+ Family Domain Pack
+ Home Assistant Connector
+ Calendar Connector
+ Email Connector
+ Cooking Skill
+ Personal Finance Skill
```

## Enterprise KARI

```text
KARI OS
+ Enterprise Domain Pack
+ Software Engineering Domain Pack
+ GitHub Connector
+ Jira Connector
+ Slack Connector
+ Code Review Skill
+ Architecture Skill
```

## Creative KARI

```text
KARI OS
+ Creative Studio Domain Pack
+ Asset Connector
+ Design Tool Connector
+ Graphic Design Skill
+ Brand Craft Skill
```

Same cognitive core.

No forked brain.

---

# 19. Customization levels

## Level 1: safe user configuration

Users may configure:

- preferences;
- personas;
- goals;
- routines;
- notifications;
- memory controls;
- tool permissions;
- installed skills;
- provider preferences within allowed policy;
- local/cloud policy;
- approval thresholds;
- autonomy level within granted maximum.

## Level 2: declarative advanced configuration

Power users/admins may define through manifests/config:

- domain schemas;
- roles;
- processes;
- relationship types;
- triggers;
- workflows;
- policies;
- prompt contracts;
- automation templates.

No Python should be required for ordinary declarative specialization.

## Level 3: extension development

Developers may add:

- Connectors;
- tool implementations;
- specialist engines;
- governed stores/projections;
- workflow adapters;
- custom UI surfaces;
- Domain Packs;
- Skill Packs.

All operate through governed extension interfaces.

---

# 20. Autonomy model

Autonomy must be explicit policy.

Proposed semantic scale:

```text
A0 Observe
A1 Recommend
A2 Prepare
A3 Approve then execute
A4 Execute within delegated scope
A5 Execute + monitor
```

## A0

```text
"Your electric bill increased 24%."
```

## A1

```text
"I recommend switching tariff plans."
```

## A2

```text
"I prepared the application."
```

## A3

```text
"Approve submission?"
```

## A4

KARI may renew a subscription under a pre-authorized threshold.

## A5

KARI may manage a recurring workflow, evaluate outcomes and escalate exceptions inside delegated scope.

A Domain Pack may request behavior.

It may not raise its own granted autonomy level.

---

# 21. Runtime Governance Profile

Every deployment should maintain machine-readable governance answering:

```text
Who/what does KARI serve?
What may KARI observe?
What may KARI remember?
How long may it retain it?
What may KARI infer?
What may KARI execute?
What requires approval?
What may never be delegated?
Which domains/connectors are enabled?
Who may change these rules?
```

Conceptually this is KARI's capability constitution.

A practical code name is:

```text
RuntimeGovernanceProfile
```

It must compose with:

- tenant policy;
- user policy;
- role policy;
- connector permissions;
- Domain Pack policy;
- action-specific policy;
- security/safety constraints.

Lower-priority rules cannot override stronger restrictions.

---

# 22. What must not enter KARI core

Do not put these directly in universal core:

- Salesforce semantics;
- Jira semantics;
- Slack semantics;
- accounting workflow vocabulary;
- healthcare vertical schemas;
- brand templates;
- family-specific rules;
- household routines;
- CRM opportunity types;
- school curricula;
- legal workflow types;
- smart-home device semantics;
- tool-specific design concepts;
- industry-specific approval chains.

These belong in Domain Packs, Skill Packs or Connectors.

Otherwise `core/` becomes a landfill of vertical semantics.

---

# 23. Live package mapping

| Current area | KARI OS classification | Current direction |
|---|---|---|
| `core/cortex` | Core cognition | Preserve as cognitive decision authority |
| `core/runtime` | Core runtime | Preserve and generalize event intake without duplicate runtime |
| `core/memory` | Core continuity | Deepen evidence/formation/longitudinal behavior |
| `core/cognitive` | Core vocabulary | Typed cognitive contracts, not orchestration |
| `core/intelligence` | Core perception/signals | Subordinate inference/signal layer |
| `core/context` | Core context | World/context assembly primitives |
| `core/personalization` | Core person/self foundation | Evolve toward generic PersonModel/relationship continuity |
| `core/adaptive` | Core adaptation | Learning/adaptation support |
| `core/automation` | Core agency, underbuilt | Expand durable commitments/triggers/wakeups |
| `core/expression` | Core output boundary | Preserve expression/output modality boundary |
| `agent_medusa` | Specialist execution | Distributed multi-agent execution only |
| LangGraph | Specialist workflow engine | True graph semantics only |
| provider/model runtime | Kernel infrastructure | Backend-owned availability/health/selection |
| auth/RBAC | Kernel authority | Never delegated to UI/pack/connector |
| plugin/extension infrastructure | Ecosystem substrate | Formalize Connector/Domain/Skill taxonomy |
| PostgreSQL/Supabase | Durable data authority | Keep canonical |
| pgvector | Vector retrieval substrate | Keep canonical |
| PostgreSQL FTS | Lexical retrieval substrate | Keep canonical |
| Redis | Hot/distributed state | Keep bounded/coordination role |
| Neo4j | Retired | Do not resurrect without ADR |
| Milvus | Retired canonical-memory projection | Do not resurrect casually |
| Elasticsearch memory projection | Retired | Do not treat as current memory stack |
| DuckDB | Retired / stale config debt | Remove stale wiring |
| Enterprise-specific logic | Domain semantics | Keep outside universal core |

---

# 24. Conceptual renames

These are conceptual language improvements, not immediate file-renaming instructions.

## Old

```text
Organizational Memory
```

## Better

```text
World + Relationship Memory
```

---

## Old

```text
Institutional Craft
```

## Better core

```text
Craft & Practice
```

## Specialization

```text
Institutional / Brand Craft Skill or Domain Pack
```

---

## Old

```text
Employee AI
```

## Better

```text
Person Model + Role Context
```

---

## Old

```text
Department Agents
```

## Better

```text
Role / Domain Specialist Agents
```

---

## Old

```text
Enterprise Automation
```

## Better

```text
Commitment & Action Runtime
```

Do not mechanically rename established authority classes. Names such as CORTEX, NeuroRecall, NeuroVault, RuntimePolicy and Agent Medusa retain project meaning until an explicit migration updates code, tests, docs and telemetry together.

---

# 25. Canonical KARI runtime cycle

```text
                 +----------------------+
                 |        EVENTS        |
                 | user/system/world    |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |      PERCEPTION      |
                 | intelligence/context |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 | MEMORY + WORLD MODEL |
                 | relevant continuity  |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |        CORTEX        |
                 | interpret / decide   |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |    RUNTIME POLICY    |
                 | authorize/constrain  |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |    EXECUTION PLAN    |
                 +----------+-----------+
                            |
            +---------------+----------------+
            |               |                |
            v               v                v
         Respond         Act/tool         Workflow
                                           Agents
            |               |                |
            +---------------+----------------+
                            |
                            v
                 +----------------------+
                 |       OUTCOME        |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |   REFLECT / LEARN    |
                 +----------+-----------+
                            |
                            v
                 +----------------------+
                 |  MEMORY / MODELS     |
                 | update continuity    |
                 +----------------------+
```

Chat is one event source.

Not the definition of KARI cognition.

---

# 26. Architecture invariants

## Runtime

- routes are thin ingress;
- CORTEX decides;
- RuntimePolicy authorizes;
- Runtime executes;
- WorkflowRuntime adapts authorized complex work;
- LangGraph never becomes global runtime;
- Agent Medusa never becomes cognitive authority.

## Memory

- Redis does not become LTM authority;
- NeuroRecall retrieves;
- MemoryFormation evaluates formation;
- NeuroVault governs durable mutation;
- PostgreSQL/Supabase remains durable authority;
- graph projections remain rebuildable unless deliberately migrated;
- no cross-tenant recall;
- no side-door writes.

## Extensions

- Connectors provide capabilities/events;
- Domain Packs provide specialized semantics;
- Skill Packs provide reusable practice;
- none may own auth, tenant identity, provider routing, memory persistence or global policy.

## Providers

- one provider/model authority;
- local-first behavior remains config/policy driven;
- no UI/provider selection split-brain;
- unavailable means unavailable, not fabricated output.

## Security

- tenant identity is server-derived;
- role/permission claims are governed;
- actions remain auditable;
- approval requirements survive workflow/agent boundaries;
- extensions cannot self-elevate autonomy.

---

# 27. Current gaps versus target

## Strong today

- PostgreSQL/Supabase durable data spine;
- pgvector semantic retrieval;
- PostgreSQL FTS;
- temporal/entity/relation memory projection;
- Redis bounded/distributed state;
- CORTEX decision authority;
- RuntimePolicy separation;
- Runtime-authoritative chat path;
- provider/model backend authority;
- Agent Medusa distributed controls;
- layered memory concepts;
- tenant/RBAC/audit hardening;
- substantial CI architecture/release gates;
- first-run durable bootstrap direction.

## Partial

- evidence-informed two-stage cognition;
- generic Person/Self/Relationship continuity;
- memory formation after actual outcome;
- longitudinal belief revision;
- current graph/workflow identity convergence;
- extension taxonomy;
- generalized event ingestion;
- installation readiness aggregation;
- first-real-chat fresh-install proof.

## Underbuilt / target

- durable commitment engine;
- wakeups/triggers/recurrence/approval lifecycle;
- universal WorldModel contracts;
- generic Craft & Practice cognition;
- first-class RuntimeGovernanceProfile;
- autonomy-level contract;
- Personal/Family/Enterprise generality benchmark;
- longitudinal cognition benchmark.

---

# 28. Current implementation program

## KARI-OS-0: architecture and stack freeze

Status: PR #58 open.

Goals:

- codify domain-neutral KARI OS boundary;
- freeze current technology truth;
- retire historical Neo4j/Milvus/Elasticsearch/DuckDB assumptions;
- distinguish Connector/Domain Pack/Skill Pack;
- establish WorldModel as contract, not database.

## KARI-OS-1: authority convergence

Finish:

```text
CORTEX
 -> RuntimePolicy
 -> Runtime
 -> WorkflowRuntime
 -> LangGraph
```

with server-derived identity/tenant context.

PR #57 is active work in this area.

## KARI-OS-2: architecture immune system

Add executable tests rejecting:

- alternate runtime authorities;
- alternate provider registries;
- alternate memory stores/writers;
- client-controlled tenant/auth graph context;
- connector self-authorization;
- vertical core leakage;
- retired Neo4j/Milvus/Elasticsearch/DuckDB authority resurrection without ADR;
- duplicate schedulers/proactive engines.

## KARI-OS-3: Universal WorldModel

Define minimum typed contracts:

```text
Entity
Person
Group
Role
RoleAssignment
Relationship
Artifact
Process
Resource
Rule
Goal
Commitment
Event
Context
Dependency
Outcome
```

Reuse existing evidence, temporal, cognitive and memory contracts.

Persist/projection-first on current PostgreSQL spine.

## KARI-OS-4: Durable Commitment Runtime

Expand canonical `core/automation` around:

- commitments;
- durable triggers;
- wakeups;
- recurrence;
- approvals;
- cancellation;
- expiry;
- context refresh;
- RuntimePolicy reauthorization;
- execution delegation;
- outcome evaluation;
- retries/follow-up;
- recovery;
- telemetry.

## KARI-OS-5: Craft & Practice

Add generic contracts for:

- Artifact;
- Exemplar;
- Technique;
- Critique;
- Constraint;
- Decision rationale;
- Outcome;
- Exception;
- Evolution.

Prove across several unrelated domains.

## KARI-OS-6: governed extension taxonomy

Formalize manifests for:

- Connector;
- Domain Pack;
- Skill Pack.

Require:

- capabilities;
- permissions;
- schemas;
- prompt contracts;
- policy requirements;
- data ownership;
- versioning;
- RBAC;
- audit;
- tests.

## KARI-OS-7: generality benchmark

Prove the same core supports:

```text
KARI Personal
KARI Family
KARI Enterprise
```

If a domain requires a core fork, treat it as architecture failure unless a new universal primitive is proven.

## KARI-OS-8: longitudinal cognition benchmark

Test:

- restart-safe commitments;
- contradiction;
- belief revision;
- preference drift;
- forgetting/retention;
- relationship continuity;
- practice learning;
- provenance;
- tenant isolation;
- context refresh before delayed action.

## TECH-DEBT-STACK-1

Audit/delete stale references to retired stack components.

Immediate known example:

```text
KARI_ENABLE_DUCKDB=true
```

still appears in compose configuration even though DuckDB is retired from current dependency policy.

---

# 29. Technology decision rule

Before adding a new datastore/framework/runtime, answer:

1. What responsibility is missing?
2. Who owns that responsibility today?
3. Can the current canonical substrate satisfy it?
4. Is this new component authoritative or derived?
5. What duplicate authority could it create?
6. What benchmark proves the existing stack is insufficient?
7. How is tenant isolation preserved?
8. How is it observed?
9. How is failure/degradation surfaced?
10. What is the rollback/removal plan?

For graph/vector work specifically, benchmark against:

```text
PostgreSQL
+ pgvector
+ HNSW
+ FTS
+ JSONB
+ temporal relations
+ recursive traversal
+ current KARI spreading activation
```

before proposing another database.

---

# 30. Developer stop conditions

Stop and run an architecture audit before merging when a change:

- creates a new global runtime;
- creates another scheduler/proactive engine;
- creates another provider registry;
- creates another memory store authority;
- writes memory outside formation/NeuroVault;
- introduces Neo4j/Milvus/Elasticsearch/DuckDB as canonical storage without ADR;
- accepts user/tenant/role authority from client-controlled payloads;
- puts vertical nouns into universal core;
- lets a Connector execute outside RuntimePolicy;
- lets a Domain Pack replace core cognition;
- lets a Skill Pack own provider selection;
- uses LangGraph for ordinary chat;
- lets Medusa decide cognitive intent;
- introduces prompt behavior without explicit prompt contracts;
- claims release readiness without exact-SHA proof.

---

# 31. Proof expectations

Backend:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
```

Frontend where applicable:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

Infrastructure/data:

```bash
docker compose config
supabase db reset
```

Architecture-affecting work must also pass applicable canonical GitHub workflows.

The current repository already contains dedicated gates for areas including:

- main quality;
- beta release;
- chat authority;
- cognitive proof;
- agent-system burn;
- Medusa;
- memory contracts;
- production auth/security;
- production database baseline;
- production deployment;
- production first boot;
- reasoning.

A workflow definition existing is not a passing verdict.

Exact-head execution is required.

---

# 32. Final architecture boundary

```text
KARI OS CORE
|
+-- Platform Kernel
|   +-- Identity
|   +-- Security
|   +-- RBAC
|   +-- RuntimePolicy
|   +-- Configuration
|   +-- Provider/Model Registry
|   +-- Secrets
|   +-- Observability
|   +-- PostgreSQL/Supabase durable data spine
|   +-- Redis distributed/hot state
|
+-- Cognitive Runtime
|   +-- Intelligence
|   +-- Context
|   +-- CORTEX
|   +-- Reasoning
|   +-- Runtime
|   +-- WorkflowRuntime
|
+-- Cognitive Continuity
|   +-- Memory
|   +-- NeuroRecall
|   +-- MemoryFormation
|   +-- NeuroVault
|   +-- Self Model
|   +-- Person Model
|   +-- Relationship Model
|   +-- WorldModel
|   +-- Temporal Model
|
+-- Agency
|   +-- Goals
|   +-- Commitments
|   +-- Prospective Memory
|   +-- Automation
|   +-- Triggers/Wakeups
|   +-- Approvals
|   +-- Outcome Learning
|
+-- Practice
|   +-- Skills
|   +-- Craft & Practice Memory
|   +-- Exemplars
|   +-- Feedback
|   +-- Adaptation
|
+-- Execution
    +-- Model Runtime
    +-- Reasoning Executor
    +-- Agent Medusa
    +-- LangGraph for real graph workflows
    +-- Extension Gateway


KARI ECOSYSTEM
|
+-- Domain Packs
|   +-- Enterprise
|   +-- Personal
|   +-- Family
|   +-- Creative
|   +-- Research
|   +-- Education
|   +-- ...
|
+-- Skill Packs
|   +-- Design
|   +-- Coding
|   +-- Research
|   +-- Writing
|   +-- ...
|
+-- Connectors
    +-- Calendar
    +-- Email
    +-- GitHub
    +-- Slack
    +-- CRM
    +-- Filesystem
    +-- Home
    +-- ...
```

---

# 33. Final principle

KARI should not accumulate separate brains for separate worlds.

KARI should provide one governed cognitive substrate capable of understanding different worlds through shared primitives.

The enduring rule is:

> **Core stores universal cognitive primitives. Packs provide semantics. Connectors provide capabilities. Runtime retains authority.**

And the current live stack makes that direction more practical than the older design:

> **PostgreSQL/Supabase is the durable memory/world spine, pgvector + FTS provide semantic/lexical retrieval, temporal relation projections provide graph-shaped continuity, Redis provides bounded/distributed state, CORTEX decides, RuntimePolicy authorizes, Runtime executes, and extensions remain subordinate.**

KARI OS becomes the cognitive substrate.

Everything else becomes a governed way of teaching that substrate about a particular world.

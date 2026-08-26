# Memory Architecture

## 1. Core rule

**Memory is the domain. NeuroRecall is how KAREN finds memory. NeuroVault is how KAREN governs durable memory.**

Do not split these concepts into competing stores.

## 2. Layers

### STM

Short-term memory holds bounded recent/session context needed for the current conversation/runtime window.

Typical backing: process-bounded state and/or Redis when configured.

Properties:

- bounded;
- session/conversation scoped;
- disposable/rebuildable where possible;
- never the sole source of durable user facts.

### Episodic memory

Meaningful interactions, decisions, outcomes, commitments, and notable events.

Properties:

- durable;
- timestamped/provenanced;
- tenant/user scoped;
- recallable by semantic/contextual strategy;
- governed by deletion/privacy policy.

### LTM

Durable facts, preferences, stable knowledge, and user/project information that remains useful beyond a single session.

Properties:

- durable source of truth;
- explicit scope and provenance;
- deduplication/update semantics;
- confidence/verification when appropriate;
- deletion/export support.

## 3. Current data architecture

Canonical durable memory uses PostgreSQL/Supabase-backed storage through KAREN's data adapters where configured. Redis may support ephemeral/session/cache functions.

**Milvus and Elasticsearch are retired from the current memory architecture.** Do not add them to deployment files, docs, recovery plans, or runtime code unless a future ADR explicitly reintroduces them with a proven requirement.

Vector/semantic retrieval should use the canonical storage capabilities selected by the current data layer rather than automatically adding a new database.

## 4. NeuroRecall

NeuroRecall owns retrieval strategy, not persistence authority.

It may own:

- query formulation;
- scope selection;
- candidate retrieval coordination;
- ranking/scoring;
- recency/relevance tradeoffs;
- recall budgets;
- deduplication/selection;
- recall reason metadata.

It must not:

- create a duplicate durable memory schema;
- bypass tenant/user scope;
- own message persistence;
- become a second vector database abstraction when canonical data adapters already exist.

## 5. NeuroVault

NeuroVault is the governance layer around durable memory.

It may coordinate:

- persistence policy;
- archive/retention;
- backup/recovery semantics;
- deletion/forgetting workflows;
- data export/governance;
- integrity/recovery controls.

It does not replace the canonical memory domain or invent another storage system.

## 6. Runtime memory flow

```text
ChatRuntime
   -> derive recall request/scopes
   -> NeuroRecall strategy
   -> canonical memory repositories/adapters
   -> ranked memory results
   -> prompt/context assembly

response lifecycle
   -> persistence
   -> memory-candidate evaluation
   -> episodic/LTM writes when eligible
   -> audit/telemetry
```

## 7. Scope and security

Every memory access must explicitly preserve applicable:

- user ID;
- tenant ID;
- conversation/session scope;
- authorization context;
- deletion/privacy status.

Never use `tenant_id="default"` as a production security fallback.

Cross-tenant recall is a critical defect.

## 8. What gets remembered

Do not persist every token as LTM.

Good durable candidates include:

- explicit preferences;
- stable personal/project facts useful later;
- decisions/commitments;
- durable configuration choices;
- important task outcomes;
- meaningful episodic events.

Poor candidates include:

- transient chit-chat;
- secrets/passwords/tokens;
- raw hidden reasoning;
- duplicate facts with no changed meaning;
- unverified guesses presented as facts.

## 9. Persistence truth

When persistence is enabled, save operations must be real. The UI must never show a fake "saved" state when the backend write failed.

Persistence metadata should capture provider/model/runtime details where relevant for provenance and diagnostics.

## 10. Recovery

PostgreSQL/Supabase backup covers the durable relational store only. Redis, object storage, model artifacts, and external services are separate recovery domains.

Recovery documentation must not imply protection for systems that are not included in the backup.

## 11. Tests

Memory work should prove:

- tenant isolation;
- write/read persistence;
- recall scoring/selection;
- deletion/forget behavior;
- restart durability;
- no legacy Milvus/Elasticsearch authority;
- no duplicate memory facade/store;
- runtime recall integration;
- failure reporting rather than fake save success.

# WS-04A: Trusted source-owner authorization, no duplicate authority

**Status:** architecture audit only; implementation and consumer acceptance **NOT** complete.  
**Baseline:** WS-02B squash merge `f0f6cd5bc8372a7e9c9f9befb7e8f97476b518b0` (#1145).  
**Scope:** Identify actual authority and tests before introducing an adapter. This file does not enable an external source, a consumer ingestion path, or a plugin.

## Confirmed repository contracts

| Current owner | Current responsibility | Boundary |
| --- | --- | --- |
| `src/ai_karen_engine/services/writing_style_sample_provenance.py` | `WritingStyleSourceAuthority.verify_analysis` protocol; `VerifiedWritingStyleSource` checks tenant/profile/owner/source/author/receipt, separate analysis/use permissions, expiry; RLS-scoped sample reference registration and evidence-first revoke | The protocol **does not** prove that a concrete production document, message, email or transcript owner is connected. Caller-provided UUIDs and attestations are never sufficient |
| `src/ai_karen_engine/services/writing_style_profile_repository.py` | Governed profile/revision/grant storage with tenant/actor scope and current publication reads | Must not become an alternate source access-control owner |
| `supabase/migrations/20261122010001_61_writing_style_sample_evidence.sql` | PostgreSQL sample immutability, grant expiry caps, lifecycle monotonicity, source revocation profile/grant fencing | Persisted receipt and snapshot are not proof of **current** external-source permission |
| `src/ai_karen_engine/core/runtime/prompt/karisignature_contract.py` | `KariSignatureResolver` checks current published revision and purpose grant, validates hash, applies bounded persona-safe presentation fields, fails closed | Expression-only prompt data; may not grant tools, system privileges, provider choice, or memory access |
| `src/ai_karen_engine/core/memory/memory_runtime_manager.py` / `src/ai_karen_engine/core/memory/retrieval/neuro_recall.py` | Trusted issuer-composed `SourceLineageAuthorizer` for graph-memory candidates | An architectural composition pattern, **not** an external source ACL owner or reusable grant database |
| `src/ai_karen_engine/core/runtime/policy/runtime_policy.py` | Existing request execution policy boundary | Only the authenticated runtime may compose trusted adapters. Ingress and UI do not authorize external sources |

See `docs/intelligent-search/KIS_GRAPH_01C2C_SOURCE_AUTHORIZER_COMPOSITION.md`. It states explicitly that production external-source permission and revocation verification are **not** provided by source references alone, and missing authorizers must fail closed.

## Source-family discovery gate

For each family below, identify the actual active production store and owner, including the authenticated actor/tenant model, author relation, ACL read/check method, current consent and expiration, revocation/deletion event or ledger, canonical ID format, and how a source can be safely retrieved. **Do not implement an adapter until this evidence exists.**

| Source family | Production owner verified by this audit | WS-04A activation |
| --- | --- | --- |
| document | Not yet verified | Disabled |
| message | Not yet verified | Disabled |
| email | Not yet verified | Disabled |
| transcript | Not yet verified | Disabled |

`source_type` values in WS-02B express allowed metadata categories, **not** live provider availability. The presence of a graph-memory `source_ref` or a previously saved receipt does not enable any family.

## Minimal trusted adapter contract

1. Compose one source-owner adapter at authenticated runtime bootstrap from a verified existing source service; reject request-supplied verifiers, source ACL results, or plugin-invented receipts.
2. `verify_analysis` must perform a **live** read of canonical tenant, source, owner, author, current ACL, consent and expiration. Fail closed for missing, deleted, revoked, cross-tenant, unowned or unauthorized sources, errors and network outages.
3. Distinguish `analysis_allowed` from `style_use_allowed`. Permission to analyze is insufficient to publish or delegate a style.
4. Treat publication and every application of a sample-backed profile as a live source-eligibility boundary. A delegate cannot rely on owner-only sample SELECT predicates under PostgreSQL RLS, stale cached grants, or snapshot consent metadata.
5. For live revocation, use existing source-owner change events/outbox if available, with idempotent profile/grant invalidation; also perform current eligibility checks at use, so event-delivery lag cannot reopen access. Do not add a competing event bus.
6. Preserve the WS-02B evidence-first row-lock order. New callbacks and database changes must be checked for deadlock order, tenant isolation, transaction race and permission bypass.
7. Log bounded correlation/source type/profile/revision/tenant/decision metadata using existing observability; no sample bytes, credentials or unrestricted content. The UI can only display backend-verified readiness.

## Execution slices

- **WS-04A1: Source owner audit:** Document concrete active source owner(s), select exactly one first source family and identify its existing permissions/revocation APIs. No owner found means fail-closed and no activation.
- **WS-04A2: Source authorization adapter:** Add a narrowly scoped implementation under the existing appropriate owner, issued only by trusted runtime composition, with current-source permission proof. Do not add new datastore, route, router or registry unless an existing canonical owner explicitly requires extension.
- **WS-04A3: Runtime publication/use fence:** Recheck live permission at publication and every purpose-specific use, while preserving the current `KariSignatureAuthority` and `KariSignatureResolver` signatures where possible. Use one authoritative runtime path.
- **WS-04A4: Revocation propagation:** Invalidate evidence-dependent published profiles/grants on verified owner revoke/delete/consent loss. Ensure revoked use is denied even before asynchronous invalidation completes.
- **WS-04A5: Authenticated acceptance:** Prove real source ownership, permission changes, revocation, tenant denial, and runtime output provenance. Consumer UI and ingestion remain separately gated.

## Test and release proof

- Correct source author/owner/tenant and independent analysis/style-use permission, including source missing or deleted, consent expiry, cross-tenant, wrong actor, denial and verifier error.
- Revoke or alter source access after sample registration but before publication; publication denied. Revoke after publication and between two delegated use requests; subsequent use denied. No authorizer available means use denied.
- Owner direct-SQL grant escalation, raw evidence mutation, published-to-draft rollback, and concurrent revoke/update cannot bypass existing PostgreSQL fences.
- Authenticated runtime tests prove source verification is issuer-composed and not injected through route metadata, plugin arguments or user prompts.
- Source-selection tests preserve `NeuroRecall` and memory source-authorizer boundaries; no second memory or ACL owner introduced.
- Required exact-head validation: targeted Python and PostgreSQL integration, import compilation, Ruff, Backend Quality, Main Quality, Production First-Boot, security review, and release/readiness audit.

**Release decision:** WS-02B is merged; WS-04A is **NO-GO for consumer activation** until a genuine source owner, a current-permission adapter, live revocation and authenticated use-path proof exist.

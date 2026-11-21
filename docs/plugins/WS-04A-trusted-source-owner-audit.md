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
| document | ArtifactStore / SupabaseArtifactStore verified as resource owner, author-style-consent owner unverified | Disabled |
| message | Conversation-owner message CRUD exists, style-source authorization unverified | Disabled |
| email | Not yet verified | Disabled |
| transcript | Not yet verified | Disabled |

`source_type` values in WS-02B express allowed metadata categories, **not** live provider availability. The presence of a graph-memory `source_ref` or a previously saved receipt does not enable any family.


## WS-04A1 source ownership investigation (verified against live repository)

### Canonical artifact storage is real, but not writing-style consent

The concrete persistent document/artifact layer is:
- `src/ai_karen_engine/services/database/repositories/artifact_store.py`: `ArtifactStore` contract, canonical `Artifact` metadata and owner-scoped operations.
- `src/ai_karen_engine/services/database/repositories/supabase_artifact_store.py`: Supabase Storage + PostgreSQL `files` backing, with `file_id`, `tenant_id`, `owner_user_id`, metadata, SHA-256, and `deleted_at`. The `list_owner_artifacts_page` operation is a metadata-listing contract, not an ACL grant.
- `src/ai_karen_engine/services/search/article_document_service.py`: saves research text as `kind='search_article'`, checks authenticated user/tenant, current owner and deleted state, and verifies bytes/citation provenance on reading.

These prove durable artifact ownership and active/deleted state for the user who saved the object. They **do not** establish that user authored the text, that a third-party author consented to writing-style analysis or imitation, or that a server-issued style-use grant is attached. A retrieved article's citation URL and user ownership of a copy are not authorization to impersonate the original writer. Do not bind `search_article` directly to a `VerifiedWritingStyleSource`, set `style_use_allowed=True` from artifact metadata, or treat `ArtifactStore.get_metadata` as consent proof.

**Implementation consequence:** The existing `ArtifactStore` and its PostgreSQL `files` records are the preferred document resource owners when a genuine style-consent source relationship can be established. Any new feature-specific consent must use the already governed consent infrastructure, issuer-signed/persisted decisions, and source-record references instead of a second artifact or ACL database. Current audit does not establish such a production association.

### Message/channel source ownership is not equivalent to authorship permission

- `server/chat/message_service.py` has conversation-owner-scoped message CRUD. Its message retrieval joins a conversation's `user_id`; its soft deletion marks message metadata. The examined contract does not prove the canonical tenant-aware, author-consent-verified production source-authorizer required by KariSignature.
- `src/ai_karen_engine/services/channels/execution.py` authenticates a claimed inbound event and enforces runtime policy before execution. It is an **execution** authority; accepting an inbound message is not permission to analyze or imitate its sender's writing style.
- `src/ai_karen_engine/services/channels/personal_pairing_policy.py` describes consent to connecting a managed personal transport. It expressly does not grant unrelated writing-style use. Connection consent must never be converted to author consent.
- No production owner plus explicit writing-style author consent and live revoke/read API was verified for email or transcript in this audit.

### Source-family eligibility after inspecting concrete owners

| Family | Existing store discovered | Verified consent + authorship + live revocation for style? | Eligibility |
| --- | --- | --- | --- |
| document | `ArtifactStore` / `SupabaseArtifactStore`; `SearchArticleService` for research documents | **No.** Artifact owner/deletion checks exist; author's explicit analysis/use rights are not established | **Disabled** |
| message | `server/chat/message_service.py` and runtime channel execution paths | **No.** Conversation ownership and transport execution are not style-use author consent | **Disabled** |
| email | No canonical style-authorizing owner verified in this audit | **No** | **Disabled** |
| transcript | No canonical style-authorizing owner verified in this audit | **No** | **Disabled** |

### Precise implementation blocker for WS-04A2

**Do not build an adapter that unconditionally allows a source because its bytes or metadata are readable.** To implement the first viable document adapter, identify or extend the *canonical source/consent owner's* existing current-permission contract to verify: exact tenant, authenticated actor, **actual source author** (not storage owner by default), source revision/deletion state, independently governed `analysis_allowed` and `style_use_allowed`, current grant expiry/revocation and receipt issuer. A source-author grant must be persisted and revocable through the canonical owner; it cannot be synthesized by KariSignature or accepted from free-form artifact metadata. Reuse the source owner's event/outbox and query current permissions at publication/use to avoid asynchronous revocation windows.

Audit proof before any code change: find the canonical consent issuer, show an authorized source decision under live tenant RLS, revoke it in the owner, then demonstrate a fresh decision becomes false. Only then implement the `WritingStyleSourceAuthority.verify_analysis` adapter against that owner and wire its live-use counterpart.

This is a **confirmed functional dependency**, not merely a missing adapter class. Building the class before trustworthy grant evidence would produce an authorization bypass rather than progress.

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

## WS-04A2 source adapter implementation (inactive)

The draft branch now contains `src/ai_karen_engine/services/artifact_writing_style_source_authority.py` and `tests/extensions/test_artifact_writing_style_source_authority.py`.

The adapter implements the existing `WritingStyleSourceAuthority.verify_analysis` contract for canonical `ArtifactStore` objects, but **requires an independently trusted `DocumentStyleConsentIssuer.verify_current`**. It supports only `document` source references and currently restricts source author, artifact owner and requesting actor to the same exact UUID. It checks current resource metadata, exact tenant and owner, permitted `kind`, active/deleted state, issuer receipt type/scope, current analysis permission, and expiry. It preserves `style_use_allowed` exactly as issued rather than inferring it from source metadata. Saved search articles and unknown source types are denied.

**Status and limitation:** No production `DocumentStyleConsentIssuer` has been proven or registered in the runtime. The adapter is deliberately not composed into the application or exposed to users. Its presence in the tree does **not** establish a consumer-ready source authorization path. A future trusted issuer must independently prove actual author consent; passing a test stub or a user-supplied object is not authorization. Source-side revocation and publication/use rechecks remain WS-04A3/4 gates.

The targeted regression file covers trusted issuer requirements, refusal to read metadata as consent, owner/tenant/author mismatch, deleted or foreign artifacts, search article denial, missing/expired/denied consent, unexpected exceptions, source type denial, and a permission changing between two calls. These cases need exact-head execution before any acceptance claim.

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

### WS-04A2 source/use recheck refinement

The inactive adapter now exposes `verify_use(...)->bool`, implemented by rechecking the same current source plus separately issued consent and requiring `style_use_allowed is True`. A source eligible only for analysis returns false for use. It also reloads canonical artifact metadata **after** the consent issuer decision and refuses archived/deleted, ownership-changed, kind-changed, or SHA-256-changed resources. Tests cover permission revoked between calls, source deletion between metadata reads, and content-revision drift.

The second read reduces a permission race but **does not** establish atomic source/consent snapshot semantics, a current-use runtime hook, or a durable author grant. Publication and every delegated runtime use remain fail-closed until the canonical issuer, transaction/fencing strategy and runtime composition are implemented and proved. Do not treat `verify_use` as a substitute for runtime policy or KariSignature purpose grants.

### WS-04A2 independent review repair, exact-head revalidation

The latest source adapter revision applies three explicit fail-closed corrections identified in the independent review:
1. A missing consent decision returns immediately after **one** metadata read; the regression assertion matches that short-circuit.
2. Artifact SHA-256 values must be exactly lowercase hexadecimal, 64 characters, on **both** resource reads; missing, nullable, uppercase, malformed and non-string values all deny source use.
3. Consent expiry is rechecked **after** the second awaited resource read, preventing a positive permission decision after the expiry passes while querying artifact metadata.

The corresponding tests exercise both digest stages and a delayed second metadata read crossing the expiry boundary. **These are review-driven fixes, not a production consent issuer or an atomic source/consent transaction.** The latest commit's CI and review must pass before these tests count as evidence. External-source author grants, owner revocation propagation, authenticated publication/use integration and consumer UI remain disabled.

## Mainline WS-02C integration discovered during reconciliation

Live `main` added `src/ai_karen_engine/services/formatting/karisignature_persisted_sample_authority.py` (WS-02C) and corresponding `tests/services/test_karisignature_persisted_sample_authority.py`. **Reuse this production-owned analysis boundary instead of introducing a second analyzer or evidence adapter.**

The existing `WritingStylePersistedSampleAuthority` already:
- Reads owner-only `writing_style_sample_evidence` joined to a draft-only canonical profile under authenticated tenant/actor scope.
- Requires the existing `WritingStyleSourceAuthority.verify_analysis` decision to match author, current consent receipt, source identity, tenant, owner, profile and expiration.
- Requests content only through the existing trusted `WritingStyleSourceContentReader` and verifies exact sample-content SHA-256 against current source bytes.
- Rechecks evidence and live source authorization after reading to deny content or consent revocation during analysis.
- Never publishes a style, owns raw documents or creates a second ACL database.

**WS-04A2 is intentionally subordinate.** Its `ArtifactWritingStyleSourceAuthority` implements the *already established* source-authorizer interface for one possible document resource, but cannot be activated until an actual author-consent issuer exists. Do not duplicate or replace the WS-02C persisted sample authority. Before runtime integration, verify whether the canonical ArtifactStore can provide WS-02C's content-reader requirement with authenticated ownership and source-digest stability; never substitute requester-provided sample bytes for a trusted source read.

Source-adapter positive decisions are not end-to-end publication or delegated use grants; those need their own current-permission, source-issuer and audit proof.

## WS-04A2 permission-race refinement after reconciled green checks

The live mainline schema audit confirmed `public.files` stores `file_id` as text, `owner_user_id` as a UUID and `sha256` as nullable text, while the source adapter intentionally accepts only canonical UUID string IDs and validated SHA-256 values. The `files` owner is a storage owner, **not** proof that this actor authored third-party document content. Existing channel-pairing or memory consent cannot be converted into author-signed style consent.

The inactive artifact adapter now issues a **second current-consent call after its final artifact metadata read**. It rejects revocation, missing decisions, changed consent receipts, author/owner/scope changes, changed explicit use rights, changed expiration and verifier failures. Focused tests exercise revocation/receipt rotation/permission expiry changes between issuer reads and require two real source metadata reads on the positive path. The adapter remains fail closed with no production consent issuer.

This is an intermediate consistency fence, **not** a serializable database transaction; consent may still change just after verification. A complete authenticated publication/use path must enforce a trusted persisted grant and transactional or monotonic revocation fence with real source-owner evidence. Reuse WS-02C's `WritingStylePersistedSampleAuthority` for analysis, not a duplicate analysis engine. Keep every source family disabled until this end-to-end proof exists.

## WS-04A4: Stop unsafe source-byte materialization before activation

The independent review of head `04fdf2eec084bc1b9407b24d6efe3800de118d0e`
identified a P2 security issue: `SupabaseArtifactStore.download` fully materializes
the storage response before callers can perform a bounded `stream.read`.
Thus the earlier `ArtifactWritingStyleContentReader` could not enforce a
64 KiB **network or memory allocation** limit, despite rejecting oversized bytes
after the download. That reader and its misleading test assumptions have been
removed from the draft. Its export is explicitly prohibited by a regression
test until a canonical bounded storage-read contract exists.

### Required canonical owner implementation before restoring content access

1. Extend the existing `ArtifactStore` contract, not a WS-specific storage
   client, with an owner-authenticated, transport-bounded source-text read.
   The storage client must prove a maximum transfer/allocation boundary **before**
   object bytes are buffered. A post-download `read(max_bytes + 1)` is insufficient.
2. Bind explicit tenant/user identity to the canonical PostgreSQL source owner,
   verify active/deleted state and immutable digest/size, and serialize source
   revocation/archive as needed. Reject metadata/storage revision drift.
3. Return only approved, bounded, digest-verified UTF-8 inert content; never
   expose storage keys or raw external-source bytes to the request or UI.
4. Reuse mainline WS-02C `WritingStylePersistedSampleAuthority` for exact
   evidence/consent/source-content agreement and its existing
   `WritingStyleSourceContentReader` contract.
5. Separately establish a real author-issued consent issuer with current
   revocation/expiry and signed or governed receipt lineage. `public.files`
   ownership and document listing remain **not** author consent.
6. Exercise oversized **actual storage objects** with deceptively small
   metadata in integration tests. Verify bytes transferred and memory consumed,
   not merely the length of a stream read after materialization.

**Current release status: NO-GO.** The metadata-only
`ArtifactWritingStyleSourceAuthority` remains inactive and requires a trusted
issuer. No document bytes can flow through the removed adapter, and the
consumer writing-style feature remains disabled. This is a defensive scope
reduction, not completion of WS-04A3 or WS-04A4.

## WS-04A4: Canonical storage capability audit and negative contract proof

Inspection of the current storage infrastructure found that `SupabaseArtifactStore.download` returns a `BytesIO` wrapping an already-fetched complete Supabase Storage object. The shared `ObjectStorageClient.get` similarly returns `bytes` rather than a verified bounded stream, and `ArtifactStore.read_owner_active_code` checks owner, size and digest but also calls whole-object `bucket.download`. These existing contracts cannot guarantee resource-bounded downloads when storage bytes disagree with DB metadata. Do **not** reuse them for user-provided writing-style source texts under a claimed transport/memory budget.

A new negative regression in `tests/extensions/test_artifact_writing_style_source_authority.py` proves the inactive metadata+issuer authorization path does not call `ArtifactStore.download` at all, including on a positive in-memory consent decision. It verifies the two metadata reads and two current issuer checks and provides a download dependency that raises if touched. This test does not establish a production consent issuer; it only fences off unsafe byte access from the current adapter.

To unblock actual WS-02C content ingestion, extend the **canonical storage owner** with an explicit owner-scoped range/stream API whose response size is enforced at the transport layer; add a backend capability check that denies when streaming/range semantics are unavailable; then test a maliciously oversized object with a deceptively small metadata size and measure actual bytes transferred. Only after source-owner proof may a KariSignature adapter use that API, subject to independently issued durable author consent, transactional revocation and runtime RBAC.

## WS-04A5: Canonical bounded-text read contract (fail-closed, not yet a backend)

The canonical `ArtifactStore` interface now includes
`read_owner_active_text_bounded(artifact_id, tenant_id, user_id, *, max_bytes=65536)`.
This method is intentionally a concrete **denial default** returning
`bounded_artifact_read_unavailable`, so all existing backends, including
`SupabaseArtifactStore`, remain unsupported until they implement a
transport-enforced byte cap. It is not a renamed `download` method and
cannot silently fall back to full-object buffering. A future implementation
must enforce owner/tenant/active checks, prohibit external-source consent
inference, cap transferred bytes before allocation, and verify the original
SHA-256 against exactly those bytes.

`tests/services/test_artifact_storage_platform_client.py` now asserts that
the inherited negative implementation returns no bytes and does not even
initialize the Supabase storage bucket. A trap bucket raises if a whole-object
download is invoked. This establishes a fail-closed contract but **does not**
prove a working streamed read or positive capability. Those tests, backend
transport support, PostgreSQL deletion fencing and author-issued consent
remain separate release gates. The WS-04A document reader remains removed
and consumer functionality disabled.

## WS-04A6: Canonical Supabase owner-ranged transport (code under review)

The existing `SupabaseArtifactStore` now overrides `ArtifactStore.read_owner_active_text_bounded` with an owner-scoped PostgreSQL `SELECT ... FOR SHARE` query followed by a **signed, short-lived HTTP Range request** to the currently configured Supabase Storage origin. No SDK `bucket.download` call occurs on this path. The URL signer is the already-initialized platform storage bucket. Every outbound signed URL must match the configured origin, expected `/storage/v1/object/sign/artifacts/<tenant>/<artifact>/<filename>` path and a nonempty token; redirected or alternate-origin targets fail closed.

The byte read requires `206 Partial Content`, an exact `Content-Range` matching the owner metadata's verified small byte size, identity encoding, bounded `aiter_raw(chunk_size=4096)` reads, exact length, the original SHA-256, strict UTF-8, and no disallowed control characters. If the backend ignores the range, returns a different object size, exceeds the cap, changes the digest, or fails its signed-link capability, it returns only `bounded_artifact_read_unavailable`. The existing owner row is locked for the duration of the storage read. The request budget is at most 65536 bytes. The URL and token are never included in API errors or structured logs.

The new regression matrix in `tests/services/test_artifact_storage_platform_client.py` uses `httpx.MockTransport` for success, full-response rejection, missing/wrong `Content-Range`, oversized response, wrong digest, untrusted host, scheme/bucket/path mismatch, absent owner and invalid budgets. These tests validate code paths without asserting a live Supabase-host result. **Independent code/security review, exact-head CI and authenticated integration against a real storage instance remain mandatory.** No WS-04A content-reader consumer is reintroduced in this slice, and no author-issued consent or runtime activation has been granted.

### WS-04A6 follow-up hardening

The signed-range reader now disallows non-loopback plain HTTP to protect the short-lived signed token in transit. A hostile incremental response regression verifies that a server emitting arbitrarily many raw chunks cannot make the application allocate beyond the declared owner-size budget: the iterator is abandoned immediately on its first over-budget chunk. The existing code remains unavailable for KariSignature until author consent and WS-02C runtime composition are implemented and proved. Live Supabase integration has not yet been executed.

## WS-04A7: Signed URL logging finding and defensive fix

Independent security review of `a7568353ce2983046bd6c09c062c28d5724c52bb` found a **P2 bearer credential exposure**: HTTPX's INFO request logs can include the signed object URL `?token=...`. Karen's supported text formatter previously emitted `record.getMessage()` unredacted. The credential could otherwise be replayed while the signed link remains valid, bypassing subsequent owner/archive checks.

This workstream now reuses the **canonical** logging redaction owner, `src/ai_karen_engine/core/logging/redaction.py`, for complete signed-URL query token removal (including short and encoded values). An idempotent `SignedStorageURLLogFilter` sanitizes HTTPX request log records **before** handlers run, preserving unrelated HTTPX INFO events. The filter is installed by both `setup_sinks()` and immediately before the signed object range read in the existing storage repository. `RuntimeTextFormatter` also invokes the same canonical redaction service, so text output does not rely solely on the transport filter. The JSON formatter already uses canonical `redact_data`.

The regression in `tests/services/test_artifact_storage_platform_client.py` exercises a real HTTPX INFO request via mocked transport, formats captured records with `RuntimeTextFormatter`, and rejects the raw token in captured records or formatted text. Short and URL-encoded token values are separately verified.

**No live Supabase storage acceptance, durable author-issued consent issuer or authenticated WS-02C runtime registration is claimed.** Treat the logging correction as unverified until new-head CI and independent review pass; keep consumer writing-style ingestion disabled.

## WS-04A7 follow-up: Canonical token spellings and live-target verification

A further P2 review finding demonstrated that percent-encoding the *query parameter name* (`?%74oken=...`) could pass `urllib.parse.parse_qs` as `token` while bypassing the literal HTTPX signed-URL redaction check. The canonical `SupabaseArtifactStore.read_owner_active_text_bounded` now checks the **raw query key is exactly `token` before making an outbound request**, as well as verifying the decoded one-token parameter set. The adversarial signed-URL tests reject encoded key names with encoded JWT separators without contacting the host. All signed-link logging uses the existing central redaction owner; do not weaken either defense.

At the current audit checkpoint, the linked Supabase project inventory does **not** expose an identifiable active AI Karen test project: the only returned project was an inactive, differently named project. It would be inappropriate to mutate or use that unrelated project for acceptance. Therefore **live authenticated storage streaming, size-transfer measurement, real post-archive denial and concurrency have NOT been verified**. A genuinely provisioned AI Karen test host with configured storage and PostgreSQL contract is a prerequisite for those tests.

No feature activation or consumer writing-style source use is authorized by this documentation or by mock HTTP transport tests.

## WS-04A7 follow-up: Encoded signed-path bypass denied

Fresh independent review of `3fefdcbd0cf105ee313575660cfef63cb87104f4` found a separate P2 logging bypass: URL validation used `unquote(parts.path)`, allowing percent-encoded path components such as `/object/%73ign/`. The HTTPX pre-handler credential redaction filter expects the **canonical literal** `/storage/v1/object/sign/`, so a noncanonical raw path could reach the network and log a live token.

The canonical `SupabaseArtifactStore.read_owner_active_text_bounded` now requires `parts.path == expected_path` **without unquoting**. This fails closed on encoded path components, including the signed route name and filename, before any HTTP request. The existing exact raw `token` query key validation remains in place. The regression matrix now includes encoded route and filename paths and uses a forbidden HTTP transport to prove rejection is pre-request.

This correction is committed but cannot be considered independently accepted until current-head code/security review and exact-head CI pass. The live authenticated Karen storage target, durable author consent and WS-02C runtime composition remain outstanding. Consumer feature remains disabled.

## WS-04A7 test evidence correction: zero outbound requests

Independent review of `9ad1b3b0488f169ccdfad5c22b15ea91129d160f` identified an invalid negative-proof assumption: the `MockTransport` handler raised `AssertionError` if an invalid signed URL reached HTTP, but the repository intentionally catches `Exception` and returns denial. Consequently, the test still passed when an unwanted network request was attempted.

The existing `test_bounded_signed_range_blocks_untrusted_urls` now **records every transport invocation** and asserts the list is empty after the repository call, including encoded query names and encoded route/filename paths. The handler returns an error response instead of relying on an exception to escape the repository. This distinguishes valid pre-request rejection from a failed request that occurred too late. No authenticated live storage acceptance or author consent has been proven.

## WS-04A7 follow-up: HTTPX asynchronous stream fixture correction

Independent review of `f4f3760694727bf3ae0f002e5c31daadaddd22b1` found that `httpx.Response(content=...)` eagerly consumes response bytes with the pinned HTTPX 0.28.1, even when returned from `MockTransport` to a caller using `AsyncClient.stream`. The repository then fails closed on `StreamConsumed`, so success tests and several intended integrity checks did not exercise their asserted behavior.

The canonical test fixture now returns `httpx.Response(stream=UnconsumedStream(...))` with an actual `httpx.AsyncByteStream`. Positive owner and multiline UTF-8 cases, the signed-token HTTPX INFO logging case, and malicious storage response fixtures use unconsumed streams. The negative response matrix additionally asserts **zero body reads** for refused status/missing/malformed content-range headers and **one actual stream read** for oversize-body and wrong-digest rejections. The existing zero-outbound-request assertions for invalid signed links remain intact.

This repairs test evidence, not production author consent or live Supabase acceptance. Fresh exact-head CI and independent review are required before the code can be merged as inactive infrastructure. Writing-style learning stays disabled.

## WS-04A7 follow-up: Require the actual signed-request HTTPX 206 log

Independent review of `b43e00521e2e21145b564f52f7e0f7c0a920e049` found that the signed-token logging regression could pass if HTTPX emitted no signed-object response event, because the test manually appended an unrelated INFO log. The test now locates a genuine HTTPX `HTTP Request: GET` event for `/storage/v1/object/sign/artifacts/` with `206 Partial Content`; it requires exactly one such record and verifies the **record message and text-formatted output** contain `token=[REDACTED]` and do not expose the bearer value. The unrelated INFO event still asserts ordinary HTTPX logging remains available, but cannot satisfy the signed-response proof. This test evidence is not a substitute for live authenticated Karen Supabase storage acceptance or author-issued consent.

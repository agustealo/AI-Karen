# 05 | Security, RBAC, evidence provenance and observability

## 1. Trust boundaries

**User input** and **web/crawled source material** are untrusted. **Browser state**, mode selection, source IDs and graph selections are requests for backend validation, not authorization proofs. **Trusted execution context** comes from authenticated kernel/runtime authority, not user-supplied `context`.

Threats: prompt-injected documents attempting tool execution or hidden system prompt disclosure, SSRF via crawling/links, tenant-crossing event IDs, revoked source lineage, duplicate/misleading citations, stale graph cache, guessed article IDs, source-to-source identity fusion, manipulated graph weight, action replay, logging secrets or PII, and UI privilege escalation.

## 2. Authorization contracts

- Every request resolves authenticated `user_id`, `tenant_id`, session/conversation/project identity, role, permissions and correlation in the **backend**.
- Plugin dispatcher `run(params, execution_context)` forwards trusted `InternetExecutionContext`. `params.context` is for search options only, never a source of elevated permission.
- Search, article read, graph view, recall and action tools enforce their own applicable policies; UI visibility does not confer execution rights.
- Deny cross-tenant `source_id`, `article_id`, `event_id`, `memory_id`, investigation ID and cursor tampering before returning any content or node count. Avoid distinguishing “exists but denied” from “does not exist” where revealing existence is sensitive.
- `NeuroRecall.RecallRequest.validate` requires a non-default tenant and user. `NeuroRecall` rejects mismatched candidates, applies memory guardrails and requires independent live `SourceLineageAuthorizer` for declared derived source lineage; without that authorizer, source-derived candidates are not trusted.
- Personal graph traversal must only expose records selected and reauthorized by the runtime; a graph path is not automatically an authorized display path.
- Permission/revocation changes invalidate persisted research views and graph cursors. A cached `authorized=true` flag is never a replacement for current ACL.

## 3. Evidence and citation truth

Evidence states are distinct:
1. **Discovered URL or search snippet**: source indicated by provider but full page may not be crawled.
2. **Fetched page evidence**: actual page content retrieved, with source URL and capture bounds.
3. **Stored article**: persisted, scope-checked document reference; may have independent revision/completeness.
4. **Extracted passage/claim**: transformation with precise originating source and extraction version.
5. **Model synthesis**: final runtime generation with *per-claim* evidence citation, model provenance and uncertainty.
6. **Graph relationship**: typed edge with supporting source IDs and verification state; graph hop or score alone is not fact proof.

In `InternetCapabilityService._build_sources`, fetched-source records set `evidence_level: fetched_page`; discovery-only rows can survive with empty content and must not be upgraded to fetched. Large documents expose `article_preview` rather than `full_content`, and `article_complete` must remain accurate.

PR #1119 proposes `evidenceGraph` as read-only `source` / `passage` nodes with `DERIVED_FROM` edges. Only exact matching fetched URLs produce those edges. This **does not** certify semantic, temporal, identity or causal relations and cannot substitute for server-governed cognitive graph traversal.

## 4. Prompt injection defenses

- Treat pages, metadata, HTML titles, snippets, extracted JSON-LD, graph labels and citations as **data**, not directives. Never promote them to system/developer instructions.
- Runtime prompt assembly uses versioned templates, explicit trusted/untrusted boundaries, token budgets and authorization gates.
- Do not parse “execute this tool” language from scraped sources as consent. Tool proposals are independent requests requiring runtime approval.
- Sanitize renderer output and links; forbid `javascript:`, `file:`, `data:` and unauthenticated internal targets as navigational source URLs.
- Crawl request URL validation must consider redirects, DNS resolution/rebinding, localhost, link-local and private-address egress; URL-scheme checks alone are **not** sufficient SSRF defense.
- Keep data reduction: no full source HTML in diagnostics/logs, no raw secrets, and no hidden reasoning traces or private provider prompts in consumer response.

## 5. Graph-specific security

| Threat | Required mitigation | Regression proof |
| --- | --- | --- |
| Cross-tenant neighbor | Scope every query, traversal hop, source and candidate | Mixed-tenant fixture returns only authorized graph |
| Inferred private association | Refuse unsupported edge or ambiguous entity merge | Two same-name identities remain separate |
| Revoked source | Live ACL and revision check; cursor invalidation | Previously accessible node disappears without leak |
| Graph amplification | Depth, fanout, node/edge count, timeout, cycle limits | Dense/cyclic graph bounded deterministically |
| Temporal spoofing | Preserve valid/observed/recorded fields and unknowns | Late backdated correction tested |
| Untrusted ontology label | Allowlisted relationship type, immutable typed edge contracts | Unknown relation rejected |
| Pseudo-memory | Require source event reconstruction, never raw edge dictionary | Orphan edge yields no memory candidate |
| Forged execution node | Only runtime receipts can mark task executed | Proposal stays proposed absent receipt |
| Output injection | Escape node and edge labels; safe URL navigation | Script/HTML in source never executes |

## 6. Observability and audit

All execution traces should join on `correlation_id` and `request_id`. Record `user_id`, `tenant_id`, `session_id`, `conversation_id` and investigation/snapshot IDs **only where policy permits** and through structured logging. Keep source details bounded and redacted.

Recommended events:

```text
search.request_received
search.intent_decision
search.capability_authorized / search.capability_denied
search.provider_selected / search.provider_degraded
search.discovery_completed
search.crawl_completed
search.article_persistence_completed / failed
search.evidence_projection_completed
search.graph_recall_started / completed / denied
search.synthesis_completed / abstained
search.response_completed / failed
search.investigation_saved / save_failed
search.action_approved / execution_completed / execution_failed
```

Existing `InternetCapabilityService` emits `internet_capability.started`, `internet_capability.completed` and degraded/timeout/permission logs with correlation metadata, and Prometheus search request, latency and source distributions. **Suggested event names above are target contracts, not claims they all exist.**

Useful metrics: provider discovery p50/p95/p99; crawl fetch success/degraded; source/snippet/fetched ratio; article completeness; citation coverage; graph nodes/edges emitted; unauthorized graph traversal count; recall timeout/degradation; memory provenance rejection; synthesis abstention; UI stale snapshot count; cancellation outcome; saved snapshot latency; build/release revision.

Telemetry **must not** log query text or private content by default. The current service's start log includes `query`; this is a privacy review target. When changing logging, preserve correlation, mode and counts without exposing raw query or page body in routine logs.

## 7. Degraded status and truthfulness

Keep separate:
- `requested_provider`, `requested_model` versus `actual_provider`, `actual_model`;
- `runtime_engine`, `fallback_level`, `response_source`;
- `degraded_mode`, `degradation_reason`;
- source failure versus retrieval success with no model synthesis;
- client-side fetch abort versus server-side worker termination;
- in-memory draft result versus durable save acknowledgement.

Never produce a canned “Karen found...” response when provider/model capability is unavailable. Give an honest evidence-only or unavailable response with appropriate status.

## 8. Threat-model review checklist

Before merging a new mode, graph node kind or action:
1. Identify user-controlled fields and source-controlled fields separately.
2. Identify exact authentication and server policy validation point.
3. Verify every foreign ID and lineage reference before display.
4. Test no source ref/graph count leak across tenant, project or revocation.
5. Verify provider/graph failures degrade without privileged fallbacks.
6. Check egress/scraper URL and redirect safety.
7. Confirm output cannot escape component text boundaries.
8. Prove logs/audit are redacted, structured and correlated.
9. Confirm caches include tenant, permissions, source revision, model policy and graph view identity.
10. Document residual threat and explicit release owner signoff.

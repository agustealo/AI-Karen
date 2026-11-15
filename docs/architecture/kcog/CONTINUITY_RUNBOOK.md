# KCOG Sprint Continuity and Recovery Runbook

> This is the primary cross-session handoff. Update after each slice and when a blocker changes the safe next action.

## Current snapshot (initial wiki, 2026-11-15)

- **Baseline:** `272e23c4b5879771294e46c2d205e3b6f3909050` on `main` at wiki creation.
- **Document status:** first review candidate, not merged until PR and exact-head checks are verified.
- **Implementation status:** KCOG-S1 00A source inventory and safety containment NEXT. No new cognitive inference capability claimed from wiki creation.
- **Known source-level hazards:** see [Capability Integrity](CAPABILITY_INTEGRITY.md).
- **CI:** not executed as part of wiki authoring. A PR must carry its own exact-head verification.
- **Runtime acceptance:** not completed for this sprint.

## Every new session starts here

1. Read this runbook, [Sprint Plan](SPRINT_PLAN.md), [Ownership](OWNERSHIP_AND_CALLGRAPH.md), [Capability Integrity](CAPABILITY_INTEGRITY.md) and [Decisions Ledger](DECISIONS_AND_EVIDENCE.md).
2. Fetch live `main` SHA, relevant open PRs and exact-head CI; never trust the baseline above as necessarily current.
3. Read changed source **and callers**, comparing the planned task against current canonical implementations.
4. Identify one smallest incomplete acceptance gate, then implement it on a branch from current main.
5. Test focused first; run broader CI. Capture exact files, SHA, metrics, failures and operational evidence.
6. Open PR. Do not merge merely because draft tests compile; require all applicable checks and evidence.
7. After merge, verify post-merge main, then update this runbook, sprint matrix and decisions ledger.

## Status transitions (must be evidence-backed)

`NOT_STARTED → AUDITING → IMPLEMENTING → TESTED_LOCALLY → CI_GREEN_EXACT_HEAD → MERGED → POSTMERGE_VERIFIED → RUNTIME_ACCEPTED`.

`BLOCKED`, `REVERTED`, `SUPERSEDED` are explicit statuses. Never skip states or label a future gate as completed.

## Continuity record for each PR

```text
KCOG task:
Objective / acceptance:
Owner and duplicate check:
Baseline SHA:
Branch / PR / exact head SHA:
Files changed:
Security review (RBAC/tenant/consent/audit/redaction):
Source tests / results:
Integration + real backend proof:
CI runs (status at exact head):
Benchmark (frozen dataset + candidate/base models + metrics):
Remaining risk / blocker:
Next task and smallest actionable step:
Post-merge main SHA (only after merge):
```

## Incident and rollback

- If new logic fabricates causality/calibration: disable its production use and retain a truthful unknown status; open regression issue, mark blocked.
- If evidence is missing, stale, cross-tenant or unverifiable: deny learning/promotion, keep approved baseline.
- If response execution fails: follow existing runtime fallback and degraded metadata; no generated substitute passed off as model output.
- If a model or adapter regresses: roll back through current registry/promotion authority; preserve evidence, tenant isolation and audit.
- If data source is revoked: exclude from new training and recall, inspect dependent artifacts for quarantine/retirement. Do not claim unlearning without proof.

## Handoff rule

Do not start a new architecture without completing the reuse audit. An incomplete live proof is a documented gate, not a reason to invent success. Continue on independently testable parts when external credentials/browser access are unavailable.

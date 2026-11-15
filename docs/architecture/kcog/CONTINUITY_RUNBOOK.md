# KCOG Sprint Continuity and Recovery Runbook

> This is the primary cross-session handoff. Update after each slice and when a blocker changes the safe next action.

## Current snapshot (S1 checkpoint, 2026-11-15)

- **Wiki and navigation:** [PR #863](https://github.com/agustealo/AI-Karen/pull/863) merged to `main` as `c18b3dfe3376a02e1c5de51e0195b9be7e0af182`.
- **KCOG-00A first containment:** [PR #864](https://github.com/agustealo/AI-Karen/pull/864) passed every exact-head check and merged as `2d8b0171b9f37f4eb1e2b32290b51d3ec36c916d`.
- **Continuity checkpoint:** [PR #866](https://github.com/agustealo/AI-Karen/pull/866) passed exact-head checks and merged as `724edec8ec12425bc193510270e6bdbb04677f30`. Post-merge Main Quality on this commit was green at inspection.
- **KCOG-00A2 causal effects/counterfactuals:** [PR #868](https://github.com/agustealo/AI-Karen/pull/868), head `92f10a63aee39735f8e4e2dca0423b9521eb2c67`, OPEN / exact-head CI pending. The proposal abstains instead of emitting guessed causal effects, scenario probabilities or responsibility scores.
- **KCOG-00B1 calibration/attribution:** [PR #869](https://github.com/agustealo/AI-Karen/pull/869), head `6d3ccda84bf8495b0fc7080b42d480bd5e0cfb0b`, OPEN / exact-head CI pending. The proposal distinguishes unknown error and unidentified causal contribution from numerical zero.
- **Current verified production claim:** no real deployed causal inference, independent metacognitive calibration or cognitive improvement benchmark has been accepted as part of this sprint.
- **Next:** verify all PR checks, merge green exact heads, then audit causal strategy reachability and tackle typed metacognitive evidence. Never fabricate success or merge against failed/pending required gates.
- **Sprint tracker:** GitHub Issues are disabled; use this versioned wiki and linked PRs.

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

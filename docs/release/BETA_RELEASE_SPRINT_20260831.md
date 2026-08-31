# AI KAREN Beta Release Sprint

**Audit date:** 2026-08-31  
**Audited release baseline:** `main@80fe99e87d610d528540e831b0d7ae8d758a68ba`  
**Sprint branch:** `release/beta-readiness-sprint-20260831`  
**Objective:** turn the existing beta contracts into an executable, protected, exact-SHA release decision and close the remaining fresh-install-to-real-chat gaps without introducing new authority.

## 1. Live audit verdict

KAREN has enough architectural substance for a beta candidate, but the repository is **not yet beta-release-approved**.

The dominant risk is no longer missing architecture. It is the gap between strong proof definitions and enforced release proof.

### Confirmed strengths

- Canonical chat runtime, CORTEX decision boundary, RuntimePolicy separation, provider authority, memory boundaries, distributed Medusa control, production auth/bootstrap, tenant isolation, and production deployment contracts all have dedicated executable tests/workflows.
- `.github/workflows/main-quality-gate.yml` defines classifier, backend, frontend, deployment, and aggregate quality jobs on `main` and pull requests.
- `.github/workflows/beta-release-gate.yml` defines an exact-SHA release gate with:
  - backend compile + architecture contracts;
  - provider/Core authority proof;
  - memory/conversation ownership proof;
  - production auth + tenant security proof;
  - real PostgreSQL auth concurrency proof;
  - production compose validation;
  - production API image build;
  - frontend mock rejection, typecheck, unit test, build, and production image build;
  - Chromium first-run Playwright proof;
  - genuine local-model inference on a dedicated self-hosted Windows runner;
  - final `beta-release-approved` fan-in job.
- The first-run backend lifecycle is durable, one-time, tenant-scoped, migration-owned, restart-proven, and audit-aware.
- No open pull requests currently compete for authority.

### Release blockers found live

#### BETA-P0-1: `main` is not protected

Current `main` reports branch protection disabled and no required status checks. A direct push can bypass every quality contract.

**Release rule:** no beta tag may be cut until `main` requires the canonical quality gate or equivalent ruleset and forbids unreviewed bypass except explicit break-glass administration.

#### BETA-P0-2: current `main` head has no attached status/check verdict

The audited SHA `80fe99e87d610d528540e831b0d7ae8d758a68ba` exposes no combined status contexts, and the connector reports no pull-request workflow runs for that exact head.

The workflow definitions exist, but the audited SHA itself is not presently backed by a visible exact-head green verdict.

**Release rule:** candidate SHA must have an observable exact-SHA successful Main Quality Gate before release promotion.

#### BETA-P0-3: beta release gate has not produced a release decision

No GitHub releases currently exist. `Beta Release Gate` runs only on `workflow_dispatch` or beta-tag pushes, so ordinary `main` success is intentionally insufficient.

**Release rule:** a candidate must execute the beta gate on the exact candidate SHA and produce the final `beta-release-approved` success before publishing release notes/artifacts.

#### BETA-P0-4: live-model proof depends on release infrastructure

The beta gate requires a self-hosted runner labeled:

- `self-hosted`
- `Windows`
- `X64`
- `karen-beta-model`

and the `beta-release` environment variables/secrets for a real model endpoint.

This is the correct anti-fake boundary, but it becomes a hard release blocker if runner health, labels, model endpoint, environment approval, or credentials are absent.

**Release rule:** prove the runner and genuine model inference before candidate tagging. Do not weaken this job into canned or mocked inference.

#### BETA-P0-5: installation readiness is still fragmented

The developer manifest explicitly marks the unified installation-readiness aggregator as not implemented. Provider/model, required memory services, governed extensions, and observability readiness remain separate truths.

**Release rule:** add a typed aggregation/view layer that consumes canonical subsystem health without moving ownership into AuthService, the route, or UI.

#### BETA-P0-6: first-real-chat fresh-install proof is still open

The manifest explicitly marks fresh-install first-real-chat proof as not implemented.

**Release rule:** after durable bootstrap, execute canonical `/api/chat` against a genuine enabled model and assert actual provider/model/runtime/degradation provenance. No static emergency text may count as a model answer.

### P1 debt that should be closed in the same sprint where practical

- Move `KARI_FIRST_RUN_TENANT_SLUG` and `KARI_FIRST_RUN_TENANT_NAME` interpretation behind canonical validated config. Do not add a second bootstrap config service.
- Expand the active first-run browser proof from Chromium-only release gating to a declared browser-support policy. Firefox/WebKit may be release-required or scheduled beta-compatibility gates, but the policy must be explicit rather than accidental.
- Bind release candidate evidence into one durable release manifest containing candidate SHA, required gate results, model provenance, deployment contract version, migrations, and known accepted beta limitations.
- Re-audit stale branches after beta candidate freeze so superseded retained branches cannot be mistaken for active release work.

## 2. Sprint priority and execution order

This sprint is intentionally narrow. Do not start new cognitive, agent, memory, or UI feature programs until the beta proof chain is closed unless they repair a release blocker.

### Task BETA-1: Protect the release authority

**Objective:** make it impossible for ordinary development flow to bypass release proof.

**Do**

- protect `main` using branch protection or a repository ruleset;
- require pull requests for changes to `main`;
- require the canonical `main-quality-gate` aggregate status;
- require branches to be current with `main` before merge if supported by the selected protection model;
- prevent force-push and branch deletion;
- keep explicit break-glass administration auditable and exceptional;
- document the exact required status names so workflow renames cannot silently unbind protection.

**Reuse**

- `.github/workflows/main-quality-gate.yml`
- existing GitHub repository governance

**Avoid**

- a second competing quality workflow;
- protecting individual low-level jobs if the aggregate job is the canonical merge decision;
- UI/manual convention as enforcement.

**Proof**

- branch/ruleset API shows protection enabled;
- required status includes canonical aggregate gate;
- a PR with a failed required check cannot merge;
- direct non-break-glass push to `main` is rejected.

### Task BETA-2: Exact-SHA main revalidation

**Objective:** obtain a trustworthy baseline before adding more release code.

**Do**

Run or repair the Main Quality Gate on the exact candidate lineage and record all failures by ownership domain:

1. classifier-burn;
2. backend-quality;
3. frontend-quality;
4. deployment-contract;
5. aggregate main-quality-gate.

If CI infrastructure creates jobs but executes zero steps, classify that as **NO VERDICT**, never green.

**Proof commands represented by the gate**

```text
python -m compileall -q src server scripts
ruff check src tests
mypy src/ai_karen_engine/core/runtime src/ai_karen_engine/core/cortex src/ai_karen_engine/core/model_runtime src/ai_karen_engine/core/memory
pytest focused architecture/runtime/chat/memory/security contracts
npm ci --no-audit --no-fund
npm run ci:forbid-mocks
npm run typecheck
npx vitest run --passWithNoTests
npm run build
docker compose ... config
```

**Exit condition:** exact candidate SHA has a successful observable Main Quality Gate.

### Task BETA-3: Canonical installation-readiness envelope

**Objective:** close the gap between `auth_bootstrap_complete` and `ready_for_chat`.

**Owner:** runtime/application composition view over existing subsystem authorities.

**Required envelope fields**

```text
component
required
status: ready | degraded | unavailable
reason_code
remediation_hint
source/provenance
observed_at
```

Top-level fields:

```text
auth_bootstrap_complete
ready_for_chat
overall_status
components[]
correlation_id
```

**Consume, do not replace**

- provider/model inventory + health;
- required memory dependency health;
- governed extension readiness;
- observability readiness appropriate to environment;
- deployment/auth readiness where needed.

**Security**

- authenticated post-bootstrap endpoint where details are sensitive;
- no secret values, raw connection strings, tokens, or credential material;
- tenant-scoped state only;
- remediation hints must be safe for the caller's role.

**Observability**

Emit structured events for readiness evaluation and component failure without high-cardinality IDs in Prometheus labels.

**Proof**

- architecture test proving aggregator does not instantiate providers/memory/extension health authorities;
- ready, degraded, unavailable component tests;
- required vs optional component semantics;
- no fake healthy defaults;
- `ready_for_chat` false when every allowed provider/model path is unavailable;
- optional extension failure does not block local chat unless policy/config marks it required.

### Task BETA-4: Finish first-run UI truth contract

**Objective:** make the production browser journey cover backend-authored setup and readiness without frontend authority leakage.

**Do**

- route fresh install from backend `first-run` state;
- complete first owner setup;
- refresh/reload and prove durable completion;
- consume typed installation readiness;
- show provider/model unavailability and degradation honestly;
- prevent fake completion/save state;
- continue into canonical chat only when backend says `ready_for_chat`.

**Proof**

- Playwright fresh-install browser burn;
- backend unavailable path;
- setup replay denial;
- refresh/restart durability;
- no client hardcoded provider/model inventory.

### Task BETA-5: Fresh-install first-real-chat burn

**Objective:** prove the complete release journey rather than isolated subsystem health.

```text
fresh database + Redis
 -> canonical migrations
 -> production API + UI
 -> first owner bootstrap
 -> installation readiness
 -> real enabled local/OpenAI-compatible provider
 -> POST /api/chat
 -> real model response
 -> persistence/reload
```

**Assertions**

- response is not static/canned/emergency model output;
- requested and actual provider/model metadata are truthful;
- runtime engine and response source are present;
- degradation/fallback metadata is correct when fallback is intentionally exercised;
- conversation is durably reloadable under the same tenant;
- no cross-tenant recall or persistence;
- correlation/request IDs allow the path to be traced.

**Reuse**

- canonical ChatRuntime;
- existing provider registry/model runtime;
- existing beta live-model harness where practical;
- existing conversation reload contract.

**Avoid**

- direct provider call as the release proof;
- route-level model invocation;
- mock model response;
- `emergency_static` accepted as successful inference.

### Task BETA-6: First-run config authority cleanup

**Objective:** eliminate the explicit direct-env-read debt without creating new configuration authority.

**Do**

- model first-run tenant slug/name in canonical validated config;
- inject/read those validated values through existing config composition;
- remove direct `os.getenv`/environment interpretation from `AuthService.create_first_admin()`;
- document defaults and validation;
- audit references so one interpretation path remains.

**Proof**

- config validation tests;
- bootstrap service tests;
- reference search proving legacy direct readers are gone;
- production first-boot smoke remains green.

### Task BETA-7: Release evidence bundle and beta tag

**Objective:** make the beta decision reproducible and inspectable.

**Do**

Before tag creation, freeze an exact candidate SHA and record:

- exact Git SHA;
- Main Quality Gate result;
- Beta Release Gate result;
- production image build results;
- migration baseline/version;
- first-run browser proof;
- real PostgreSQL auth concurrency result;
- real-model provider/model/runtime provenance;
- known beta limitations and accepted P1/P2 debt.

Run `Beta Release Gate` against that exact SHA. Only after the final `beta-release-approved` fan-in is green may a beta GitHub Release be published.

**Tag convention:** `beta-<semver-or-sequence>` or `v<semver>-beta.<n>` using the existing workflow trigger contract.

**Rollback rule:** a failed candidate is not retagged in place. Fix on a new SHA and create a new candidate tag/version.

## 3. Beta go/no-go matrix

| Gate | Required for beta | Current audited state |
|---|---:|---|
| `main` protected | YES | **FAIL** |
| Required aggregate merge check | YES | **FAIL / not enforced** |
| Exact-head Main Quality Gate | YES | **NO VERDICT on audited head** |
| Production auth/bootstrap | YES | implemented, must reprove on candidate |
| Tenant isolation | YES | contract exists, must reprove on candidate |
| Production compose + images | YES | gate exists, must execute on candidate |
| Frontend no-mock/typecheck/test/build | YES | gate exists, must execute on candidate |
| Browser first-run journey | YES | Chromium gate exists, must execute on candidate |
| Installation readiness aggregation | YES | **OPEN** |
| First real chat after fresh install | YES | **OPEN** |
| Genuine model inference | YES | gate exists, runner/env must prove it |
| Exact-SHA beta fan-in approval | YES | **NOT YET RUN/APPROVED** |
| GitHub beta release | YES | **NONE** |

## 4. Sprint stop conditions

Stop and repair rather than merge when any of the following occurs:

- CI job exists but executes zero steps;
- provider/model metadata does not match actual execution;
- UI can mark setup/readiness complete without backend persistence;
- fallback bypasses RuntimePolicy, tenant, or audit boundaries;
- first-run creates schema at runtime;
- bootstrap can create a second first owner;
- readiness aggregator becomes a new provider/memory/extension authority;
- release proof calls a model directly instead of canonical `/api/chat`;
- secrets appear in logs, readiness payloads, screenshots, or artifacts;
- a candidate tag points to a SHA that has not passed the exact-SHA beta fan-in.

## 5. Deferred until after beta candidate

Do not make these beta blockers unless the release burn reveals a concrete failure in them:

- broader cognitive-continuity research expansion;
- new agent topologies;
- new provider families;
- memory feature expansion beyond release-critical persistence/tenant correctness;
- visual polish not tied to first-run/chat/error truth;
- speculative framework additions.

The beta sprint is a narrowing funnel: **protect -> revalidate -> aggregate readiness -> prove browser setup -> prove real chat -> execute exact-SHA release gate -> publish**.

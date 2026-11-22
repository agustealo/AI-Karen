# Development validation policy

Karen is pre-consumer. Development iteration and consumer certification are distinct operations.

## DEV_FAST
Every pull request receives the lightweight `DEV_FAST Focused Validation` check. It parses changed Python and workflow YAML and checks changed Python for correctness errors. This check is **not** a substitute for domain-specific unit, integration, authorization, RLS, or real-database tests. Authors run affected tests during implementation and record their commands and results in the PR.

## MERGE_GATE
When a change is consolidated and ready to merge, remove its draft status and apply the `ci:merge-gate` label. The Main Quality Gate and Production First-Boot Smoke run on the PR only at this stage; later commits to a labeled PR trigger fresh checks. Remove the label during another correction cycle to avoid repeatedly starting expensive suites. Label changes also trigger gate reevaluation. GitHub `push` to `main` remains covered.

Security, authentication, tenant isolation, memory persistence, transaction rollback, plugin permissions, financial integrity, and migrations require their **relevant** real integration and regression evidence even before consumer readiness. Do not merge known P0/P1 defects or represent stale results as validation of a changed revision.

Other path-filtered workflows continue to run according to their existing triggers until their owners have audited and migrated them. This first rollout does **not** claim that all CI has been moved to staged validation.

## RELEASE_CERTIFICATION
A release candidate must pass the full exact-revision gate, real deployment and service proofs, and observed consumer end-to-end acceptance. Certification is specific to the tested revision and deployment artifact. It cannot be inherited from a previous commit.

## Operational safeguards
- Never bypass GitHub branch rules or required status checks. Review protected-branch rules before marking any new check required or retiring an existing one.
- Keep pull requests small, consolidate related review findings, and avoid merging on unresolved P0/P1 concerns.
- Preserve CI on `main` and manual `workflow_dispatch` entry points.
- Record relevant test results and remaining risks in the PR description.
- For a release or high-risk merge, use the label and keep it in place through final CI; any later commit invalidates the previous result.

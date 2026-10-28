# Capability baseline v1

This baseline prevents architectural work from silently forgetting a known product capability.
It complements existing runtime registries and tests. It does not control model routing,
plugin eligibility, or production feature flags.

## Status and evidence

`baseline.v1.json` identifies durable capability IDs, intent, canonical ownership,
known implementation evidence, related PRs and required proof. Its conservative
statuses are **not** deployment or runtime observations. Never infer that a
component works merely because the file exists, a PR was merged, or a unit test passed.

Initial tracked capabilities:
- AG-UI streaming and assistant-ui integration
- provider/model selection and execution receipts
- historical CopilotKit integration
- governed generative presentation
- persona preference persistence
- search article persistence
- model lifecycle management

Other capabilities remain to be discovered. Not listed does not mean absent or retired.

## Verification

Run:

```bash
python scripts/architecture/verify_capability_baseline.py
pytest tests/architecture/test_capability_baseline_contract.py -q
```

The verifier checks stable IDs, required owner/intent/proof, duplicate records,
repository-local evidence paths and status vocabulary. It deliberately rejects
static claims of `verified` or `consumer_ready`. Those states require a
separate signed or CI-linked runtime/consumer evidence protocol before this
schema may authorize them.

## Required next stages

1. Discover actual frontend imports, runtime API route mounts, dependency locks,
   feature-flag states, and import graph for CopilotKit, assistant-ui and AG-UI.
2. Capture introducing and replacing commits/PRs with precise behavioral diffs,
   not merely keyword matches.
3. Add a generated capability impact report to existing quality workflows. Validate
   affected ownership and run relevant tests on changed paths.
4. Implement real end-to-end evidence collection, authenticated browser test runs,
   lifecycle proof, and environment-specific verification receipts.
5. Require explicit successor capability IDs and reference/test/security audits
   before removals, without preventing safe unrelated work.

Do not turn this registry into an execution router, second memory system,
parallel configuration service or a replacement for existing architecture tests.

# COG-EVAL-1 Defect Registry

This file records defects exposed by the `tests/cognitive` benchmark that are
not fixed by the current source tree.

## Current Status

No open defects are exposed by the cognitive benchmark as of the current
contract update. The previous meta-cognition enum compatibility issue is now
covered by the upstream `MetaReasonCode.CONFLICTING_EVIDENCE` compatibility
member and the benchmark scenarios run as passing assertions instead of
`xfail` documentation.

The deterministic report remains available with:

```bash
python -m benchmarks.cognitive.report
```

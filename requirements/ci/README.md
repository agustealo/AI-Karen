# CI Python Dependency Authority

This directory owns focused Python dependency profiles for GitHub Actions proof workflows.

Rules:

- Production runtime dependencies remain owned by the root `requirements.txt`.
- GitHub workflows must not maintain ad hoc `pip install package...` lists.
- Focused proof jobs install the smallest profile that satisfies their contract instead of the full ML/runtime dependency estate.
- Linux proof workflows use Python 3.11 unless a workflow is explicitly testing a different Python version.
- Shared dependencies belong in the lowest common profile and overlays include them with `-r`.
- Runtime-pinned direct dependencies must use the same version here when they overlap with `requirements.txt`.
- Deterministic lock/constraints generation is a separate follow-up. Do not hand-invent transitive pins.

Profiles:

- `base.txt`: minimal test/config contract dependencies.
- `classifier-lite.txt`: lightweight classifier matrix proof.
- `runtime-contract.txt`: focused runtime/auth/memory contract surface.
- `quality.txt`: Main Quality static and architecture proof overlay.
- `chat.txt`: chat authority proof overlay.
- `reasoning.txt`: reasoning proof overlay.
- `cognitive.txt`: cognitive benchmark/authority proof overlay.

When a proof workflow needs a new Python package, add it to the correct profile instead of embedding it in workflow YAML.

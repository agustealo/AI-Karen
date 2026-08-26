# AI KAREN Developer Documentation

This directory contains the current developer-facing architecture and engineering contracts for AI KAREN.

## Reading order

1. [`../../PROJECT_DEV_MANIFEST.md`](../../PROJECT_DEV_MANIFEST.md) — project-wide rules, stack, authority map, do/don't list, and proof expectations.
2. [`ARCHITECTURE_AUTHORITY.md`](ARCHITECTURE_AUTHORITY.md) — detailed ownership/topology boundaries.
3. [`STACK_APIS_FILE_STRUCTURE.md`](STACK_APIS_FILE_STRUCTURE.md) — languages, frameworks, APIs, external integration rules, and file placement.
4. Read the subsystem document matching the code you will change.

## Subsystem docs

- [`CORTEX_RUNTIME.md`](CORTEX_RUNTIME.md) — CORTEX decision authority, ChatRuntime execution authority, cognitive contracts, assistant profile boundaries.
- [`MEMORY.md`](MEMORY.md) — STM, episodic, LTM, NeuroRecall, NeuroVault, PostgreSQL/Supabase, Redis, scope/governance.
- [`REASONING_LANGGRAPH_MEDUSA.md`](REASONING_LANGGRAPH_MEDUSA.md) — canonical reasoning, LangChain usage rules, LangGraph boundaries, AgentMedusa topology.
- [`EXTENSIONS_TOOLS.md`](EXTENSIONS_TOOLS.md) — extension manifests, permissions, ActionExecutionGate, credentials, lifecycle and APIs.
- [`SECURITY_OBSERVABILITY.md`](SECURITY_OBSERVABILITY.md) — auth/RBAC/tenant/security rules, telemetry, metrics, health/readiness, degraded truth.
- [`REPOSITORY_ENGINEERING.md`](REPOSITORY_ENGINEERING.md) — file/folder rules, DRY methodology, cleanup classification, configuration, deletion process.
- [`TESTING_RELEASE.md`](TESTING_RELEASE.md) — proof commands, architecture tests, provider/prompt/memory/security tests, beta/release gates.

## Documentation status vocabulary

Every architecture document should be interpreted using these labels:

- **Canonical**: current supported owner/path.
- **Transitional**: still live, but authority is moving or the component is scheduled for removal.
- **Historical**: useful record of a completed/retired sprint or incident, not current architecture authority.
- **Forbidden**: deliberately retired or disallowed design that must not be reintroduced without a new accepted architecture decision.

## Source-of-truth policy

When documentation conflicts:

1. check `PROJECT_DEV_MANIFEST.md`;
2. check the matching developer doc here;
3. check accepted/current ADRs;
4. verify live code and architecture tests;
5. treat old sprint summaries, incident documents, and migration sheets as historical unless explicitly marked canonical.

If the live implementation has changed architecture, update these docs as part of the same work rather than leaving documentation repair for later.

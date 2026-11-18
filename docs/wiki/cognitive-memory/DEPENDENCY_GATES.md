# Dependency, licensing and operational gates

**Default budget: zero new runtime dependencies, zero new services, zero new databases.**
The table below is an **initial exact-manifest inspection**, not a solved dependency lock or measured deployment size. Full direct + transitive + native + model costs are pending.

| Project | Upstream Python / license | Direct dependency / service red flags | Comparison against KAREN |
| --- | --- | --- | --- |
| LightRAG | >=3.11 / MIT | `networkx`, `nano-vectordb`, `google-genai`, `json_repair`, `pypinyin`; PostgreSQL graph mode available | KAREN has PostgreSQL graph already; package would duplicate storage and ingestion |
| Graphiti | >=3.10 / Apache-2.0 | `neo4j>=5.26` required by base package, `posthog` in core, graph DB/server for typical use | New graph service and separate authorization/retention contract |
| Cognee | >=3.10,<3.15 / Apache-2.0 | Large base includes `lancedb`, `ladybug`, `fastembed`, `onnxruntime`, `litellm`, `networkx`, `dlt`; Postgres graph module named `postgres_demo` | Very broad footprint and another ingestion/persistence owner |
| HippoRAG 2 | >=3.10 / MIT (confirm redistribution notices) | Pins `torch==2.5.1`, `transformers==4.45.2`, `igraph==0.11.8`, `openai>=3.3.1,<4`, `litellm==1.73.1` | **Known direct version conflict:** KAREN pins `openai==2.32.0` |
| Semantica | >=3.11.5,<3.14 / MIT | Base `numpy>=2`, `scikit-learn>=1.7.2`, `networkx`, `rdflib`, `grpcio`, `pyarrow`; optional extra stacks add graph/vector services | Broad core for a narrower provenance/temporal technique |

Pinned manifests: [LightRAG](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/pyproject.toml), [Graphiti](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/pyproject.toml), [Cognee](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/pyproject.toml), [HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/pyproject.toml), [Semantica](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/pyproject.toml), [KAREN](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/requirements.txt).

## Hard-stop gates
1. **Authority:** No duplicate runtime, CORTEX policy engine, NeuroVault mutation, NeuroRecall fusion or registry.
2. **Isolation:** Explicit tenant/user authorization at *every* graph hop and derived lookup; never trust unscoped IDs supplied by a model.
3. **Consent/erasure:** Source revocation must invalidate cached vectors, relationships, evidence, and derived summaries; restart/replay must preserve deletion.
4. **Licensing:** Check upstream `LICENSE`, direct and transitive SPDX, source attribution, notices, model licenses, commercial restrictions and provenance of adapted code. Avoid unlicensed copy/paste.
5. **Security:** Review CVEs, default telemetry/egress, raw document exposure, model calls, data-retention behavior and prompt-injection boundaries.
6. **Resources:** Measure new Python wheel size, transitive dependency count, native code, image delta, model weights, RAM, p95 latency, cold start, CPU/GPU and ops footprint.
7. **Compatibility:** Solve against **actual pinned KAREN runtime**, Python, OS/arch and package lock in an isolated environment; *do not adjust production pins to satisfy a research library*.
8. **Quality:** Reject if it does not outperform existing KAREN capability under [benchmark contract](BENCHMARK_CONTRACT.md) or if it violates any security gate.

## Required cost sheet for any proposed addition
`name, purpose, exact version, upstream license, direct packages, transitive delta, native binaries, extra services, model downloads, network egress, CPU/RAM/disk, p50/p95 latency, attack surface, vulnerability status, rollback, baseline delta, owner, ADR`.

**Selection order:** (1) optimize existing KAREN algorithm; (2) reuse already installed approved library/API; (3) write a bounded pure-Python/Postgres algorithm; (4) consider new package only with objective evidence and written ADR. No install is automatically justified by vendor benchmark claims.


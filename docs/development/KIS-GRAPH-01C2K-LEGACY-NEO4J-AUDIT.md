# KIS-GRAPH-01C2K: legacy Neo4j client retirement

## Scope and observed evidence

Source inspected against live `main` at `842ba6c4457364cce2bc3d1ddb16ebd4d5a9efe8`, before this branch.

- `src/ai_karen_engine/services/knowledge/knowledge_graph_client.py` was the only file whose **path** matched `knowledge_graph`, `neo4j` or `graph_client` in the inspected 4,853-entry repository tree. A path-only tree audit **does not prove** that it has no references in other files.
- `src/ai_karen_engine/services/knowledge/__init__.py` re-exports `KnowledgeGraphClient`; the import is an existing public compatibility contract.
- The legacy class opened a direct `py2neo.Graph` connection with hardcoded localhost and `neo4j`/`changeme` defaults; a connection probe occurred at construction time. It exposed raw `execute_cypher`, graph traversal/export, CRUD and `clear_all`.
- `clear_all` rejected explicitly non-admin role sets but accepted missing `rbac_ctx` in nonproduction contexts. Query/traversal methods had no mandatory tenant, user, source lineage, current consent or authorization checks. The logging decorator included exception text from graph operations, with potential to expose sensitive query parameters.
- The canonical memory graph is `src/ai_karen_engine/core/memory/graph/service.py`, backed by the PostgreSQL `GraphRepository`. Raw graph candidates are revalidated against canonical events; final selection and external source ACL are owned by `NeuroRecall`. `project_selected_memory_graph` is the selected-evidence display boundary.
- The neighboring `IndexHub` already follows a fail-closed compatibility pattern for a retired knowledge backend.

## Classification and disposition

**Dangerous legacy independent execution authority, active public import, runtime consumers not proven.** A repository Python-source reference scan is now enforced by the targeted architecture test across `src`, `server`, `scripts`, `plugins`, and `free_plugins`, excluding only the compatibility implementation, its public package export and the test itself. This does not cover dynamic imports or non-Python and external consumers; do not claim all callers were migrated.

Retire the legacy Neo4j implementation and retain the importable public class and historical exception names. Construction always raises a typed `KnowledgeGraphUnavailableError` before I/O, including when the caller passes a URI or credentials. The class exposes no callable query, mutation, raw traversal or destructive operation. This is a hard stop, not a synthetic success, shadow query, fallback database, or dynamic runtime discovery.

Existing integrations that attempt to instantiate this unsupported client will now encounter an explicit unavailable error. This **intentional compatibility change** is safer than silently bypassing tenant/source authorization. Such integrations must use the canonical runtime-authorized graph path, not direct PostgreSQL adapter calls without NeuroRecall.

## Proof and residual risk

- `pytest tests/architecture/test_legacy_neo4j_graph_boundary.py -q`
- `python -m compileall -q src`
- `ruff check --select E4,E7,E9,F src/ai_karen_engine/services/knowledge tests/architecture/test_legacy_neo4j_graph_boundary.py`
- Main Quality executes the new regression, including a repository-wide Python direct-reference audit. A new direct use will fail CI rather than invoking the retired class.
- Review PR's exact-head checks and remaining comments before merging.

**Residual risks:** external callers, dynamically computed imports and non-Python integrations may depend on the removed instance methods; the static Python scan does not establish their absence. Follow-up work must inventory references in routes, plugins, scripts and deployments and adapt genuinely active consumers through the canonical runtime without granting direct memory-graph access. No migrations or historical persisted data have been deleted.

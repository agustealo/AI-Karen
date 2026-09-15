# CORE-SPLIT-2 Developer Sheet

> **Status:** HISTORICAL / SUPERSEDED  
> **Superseded on:** 2026-09-14  
> **Current developer execution sheet:** `KARI_OS_DEV_SHEET.md`  
> **Canonical developer contract:** `PROJECT_DEV_MANIFEST.md`

CORE-SPLIT-2 was a foundational refactoring sprint for separating core/platform/runtime concerns and building the cognitive-memory lifecycle. Its useful architectural results have been absorbed into the current KARI OS methodology.

Do not use this file as the active sprint plan.

Current implementation work, live technology truth, ownership boundaries, retired-stack status, proof requirements, KARI-OS-0..8 program, LangGraph authority convergence, WorldModel direction, durable commitments, extension taxonomy and longitudinal cognition work are maintained in:

1. `PROJECT_DEV_MANIFEST.md`
2. `KARI_OS_DEV_SHEET.md`
3. `docs/architecture/KARI_OS_CURRENT_BLUEPRINT.md`
4. `docs/architecture/KARI_OS_MANIFEST.md`
5. `docs/architecture/KARI_OS_ADVERSARIAL_BURN.md`

## Historical contribution retained

CORE-SPLIT-2 established or reinforced several rules that remain active:

- core/platform/provider/extension boundaries require executable architecture tests;
- memory authority must be decontaminated from provider/platform concerns;
- cognitive contracts should remain typed and domain-neutral;
- compatibility shims need owners and sunsets;
- tenant scope must be explicit;
- policy/security boundaries must dominate execution;
- memory lifecycle must distinguish recall, formation, persistence, temporal behavior and forgetting;
- dead/duplicate authority should be deleted after reference audit;
- CI is proof, not documentation.

Those principles now live in the canonical KARI OS developer contract.

## Do not revive historical stack assumptions

The current canonical durable data/memory spine is PostgreSQL/Supabase with pgvector, PostgreSQL FTS and temporal/entity/relation projections, plus Redis for bounded/distributed state.

Neo4j, Milvus, Elasticsearch memory projections, Kuzu, DuckDB and hnswlib are not current canonical memory authorities.

See `KARI_OS_DEV_SHEET.md` for the current technology classification and sprint program.

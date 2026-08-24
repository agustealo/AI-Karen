# ROOT-CLEANUP-1A Classification & Migration Report

**Date:** 2026-08-24  
**Objective:** Repository root normalization and legacy authority collapse  
**Status:** Phase 1 complete - Classification done, safe moves pending

---

## Executive Summary

The repository root contains significant structural issues:

1. **CRITICAL:** Duplicate `server/` authority at root (506MB, 203 files) vs canonical (1.4MB, 88 files)
2. **High-value extension system** in root `server/` with sophisticated RBAC, permissions, health monitoring, and config validation
3. **Excessive documentation clutter** (20+ markdown reports, 3 PDFs)
4. **Scattered utility scripts** (14+ admin/diagnostic/migration scripts)
5. **Suspicious files** (18KB `head_version.txt` containing React code, zero-length `.codex`)
6. **Runtime state in git** (empty `.db` files, `data/automation_jobs.json`)

**Key Finding:** The root `server/` directory contains a mature extension system that should be preserved and migrated, not deleted.

---

## Detailed Classification

### 1. DUPLICATE AUTHORITY: Root `server/` Directory

**Status:** 🚨 CRITICAL - Preserve and migrate, DO NOT DELETE

**Size:** 506MB (203 files) vs canonical 1.4MB (88 files) = **360x larger**

**Import Analysis:**
- `start.py` imports from root `server/` (3 imports: `app`, `run`, `config`)
- NO imports found in `src/` from root `server/`
- Docker Compose files do NOT reference root `server/` directly

**High-Value Extension Components (17 files, ~400KB):**

| File | Size | Purpose | Migration Priority |
|------|------|---------|-------------------|
| `extension_permissions.py` | 29KB | Comprehensive permission system with roles, scopes, inheritance | **HIGH** - Migrate to `src/ai_karen_engine/extensions/permissions.py` |
| `extension_rbac.py` | 21KB | Advanced RBAC with role hierarchy, caching, tenant policies | **HIGH** - Merge with canonical permissions system |
| `extension_health_monitor.py` | 33KB | Health monitoring with Prometheus integration, background tasks | **HIGH** - Enhance canonical `health.py` |
| `extension_config_validator.py` | 51KB | Config validation with health checks, security validation | **HIGH** - Migrate to extensions config validation |
| `extension_error_recovery_manager.py` | 36KB | Error recovery and service healing | **MEDIUM** - Add to lifecycle management |
| `extension_service_recovery.py` | 35KB | Service recovery orchestration | **MEDIUM** - Add to lifecycle management |
| `extension_config_hot_reload.py` | 31KB | Hot-reload configuration changes | **MEDIUM** - Add to config management |
| `extension_environment_config.py` | 41KB | Environment-specific configuration | **MEDIUM** - Integrate with config system |
| `extension_tenant_access.py` | 25KB | Tenant isolation and access control | **MEDIUM** - Integrate with permissions |
| `extension_permission_api.py` | 25KB | REST API for permission management | **LOW** - Can be rebuilt |
| `extension_config_api.py` | 20KB | REST API for configuration | **LOW** - Can be rebuilt |
| `extension_error_recovery_api.py` | 18KB | REST API for error recovery | **LOW** - Can be rebuilt |
| `extension_auth_integration_helpers.py` | 21KB | Auth integration utilities | **LOW** - Can be rebuilt |
| `extension_auth_visualizer.py` | 21KB | Auth visualization tools | **LOW** - Documentation/analysis only |
| `extension_config_integration.py` | 18KB | Config integration helpers | **LOW** - Can be rebuilt |
| `extension_request_logger.py` | 19KB | Request logging for extensions | **LOW** - Can use standard logging |
| `validate_extension_config.py` | Small | Config validation CLI | **LOW** - Can be rebuilt |

**Other Root Server Components:**
- Standard FastAPI app structure (`app.py`, `run.py`, `config.py`, etc.)
- Chat subsystem with providers, error handling, WebSocket support
- Database migrations and health monitoring
- Deployment scripts and configuration
- Large model files in `models/transformers/gpt2/` (~500MB)

**Recommendation:** 
1. **Migrate high-value extension components** to canonical `src/ai_karen_engine/extensions/`
2. **Consolidate duplicate core server functionality** into canonical location
3. **Delete root `server/`** only after migration is complete and tested

---

### 2. DOCUMENTATION CLUTTER

**Status:** 📁 MOVE - Organize into proper structure

#### Active Architecture/Reference Docs (Move to `docs/architecture/` or `docs/reference/`)
- `CORE_CONVERGE_5_REFERENCE_MATRIX.md` (11KB) - Architecture reference
- `DYNAMIC_MODEL_DISCOVERY.md` (12KB) - Runtime discovery documentation  
- `DEPLOYMENT_QUICK_REFERENCE.md` (6KB) - Deployment guide
- `Agent.md` (23KB) - Agent documentation

#### Historical Migration Reports (Move to `docs/archive/migrations/`)
- `DEGRADED_MODE_FIX_SUMMARY.md` (6KB) - Legacy fix summary
- `FINAL_IMPLEMENTATION_SUMMARY.md` (18KB) - Implementation summary
- `LANGGRAPH_MIGRATION_SUMMARY.md` (10KB) - Migration report
- `STREAMING_FIRST_IMPLEMENTATION.md` (11KB) - Implementation history

#### VLLM/Runtime Reports (Move to `docs/archive/runtime/2026-04/`)
- `VLLM_*.md` (6 files) - VLLM implementation reports
- `vllm_audit_report_*.md` (2 files) - Audit reports  
- `vllm_configuration_mismatches_report.md` (13KB) - Configuration audit
- `LLAMACPP_RUNTIME_STATUS.md` (11KB) - Runtime status
- `MEMORY_ERROR_DIAGNOSTIC.md` (10KB) - Diagnostic report
- `PROVIDER_MODEL_ALIGNMENT_*.md` (2 files) - Provider alignment docs

#### Runtime Refactor Reports (Move to `docs/archive/runtime-refactor/2026-04/`)
- `runtime_refactor_reports/` directory (7 files, 236KB total)
- All dated 2026-04-24, clearly historical artifacts

#### PDF Files (DELETE or Move to `docs/generated/`)
- `Agent.pdf` (146KB) - Generated from Agent.md
- `DEPLOYMENT_QUICK_REFERENCE.pdf` (117KB) - Generated from markdown
- `VLLM_AUDIT_SUMMARY.pdf` (96KB) - Generated report
- `scripts/README.pdf` - Generated documentation

**Recommendation:** 
- Move active docs to organized `docs/` subdirectories
- Archive historical reports by date/topic
- Delete generated PDFs (prefer markdown source)

---

### 3. UTILITY SCRIPTS

**Status:** 🔧 ORGANIZE - Move to structured `scripts/` hierarchy

#### Administration Scripts (Move to `scripts/admin/`)
- `create_admin.py` (2KB) - Admin user creation
- `update_admin_password.py` (0.5KB) - Password management  
- `hash_admin_password.py` (247B) - Password hashing
- `verify_hash.py` (275B) - Hash verification

#### Diagnostic Scripts (Move to `scripts/diagnostics/`)
- `audit_connectivity.py` (4KB) - Connectivity auditing
- `check_api.py` (746B) - API health checks
- `check_runtime_status.py` (647B) - Runtime status
- `check_services_debug.py` (1KB) - Service debugging
- `check_plugin_issues.py` (6KB) - Plugin diagnostics

#### Migration/Refactor Scripts (Move to `scripts/migrations/`)
- `migrate_orchestrators.py` (26KB) - Orchestrator migration
- `update_imports.py` (5KB) - Import path updates
- `fix_doubled_imports.py` (877B) - Import fixing

#### Model Scripts (Move to `scripts/models/`)
- `download_model.py` (2KB) - Model downloading

**Recommendation:** Organize into functional subdirectories under `scripts/`

---

### 4. DEPLOYMENT & DEV SCRIPTS

**Status:** 🚀 ORGANIZE - Move to appropriate `scripts/` subdirectories

#### CUDA/Deployment Scripts (Move to `scripts/deploy/`)
- `deploy-cuda.sh` (3KB) - CUDA deployment
- `health-check-cuda.sh` (4KB) - CUDA health checks
- `performance-test-cuda.sh` (4KB) - CUDA performance testing
- `stop-cuda.sh` (725B) - CUDA shutdown
- `update-cuda.sh` (822B) - CUDA updates

#### Dev/Setup Scripts (Move to `scripts/dev/`)
- `setup_venv.sh` (2KB) - Virtual environment setup
- `run_karen.sh` (2KB) - Main launcher (may stay at root)
- `start_docker_services.sh` (1KB) - Docker service management
- `status.sh` (2KB) - Status checking

**Recommendation:** Keep `run_karen.sh` at root if it's the primary documented interface, organize others

---

### 5. ROOT TEST FILES

**Status:** 🧪 MOVE - Relocate to proper test structure

- `test_discovery.py` (596B) - Move to `tests/integration/test_discovery.py`
- `test_milvus_conn.py` (889B) - Move to `tests/integration/memory/test_milvus_conn.py`
- `conftest.py` (349B) - Keep at root if providing pytest-wide fixtures

---

### 6. SUSPICIOUS/PROBLEMATIC FILES

**Status:** ⚠️ AUDIT - Investigate before action

#### High Priority Issues
- `.env.local` (169B, committed to git) - Contains only comments, but should be gitignored
- `head_version.txt` (18KB) - Contains React/TypeScript code, appears to be accidental commit
- `.codex` (0 bytes) - Empty file, unknown purpose
- Empty database files: `auth.db`, `auth_sessions.db` (0 bytes each)
- `data/automation_jobs.json` - Empty runtime state committed to git

#### Other Issues
- `setup/` directory - Nonstandard packaging with `poetry.lock` (647KB) and `setup.py` (2.6KB)
- `scratch/` directory - Contains `test_search_providers.py` (2KB) experimental code
- `logs/`, `cache/`, `backups/`, `model_cache/` - Runtime directories that shouldn't be in root
- `core.50`, `core.51` - Unknown files, possibly temporary/runtime

**Recommendation:** 
- Delete `.env.local`, empty database files, and obvious garbage
- Audit `head_version.txt`, `.codex` before deletion
- Move `scratch/` content to tests or delete
- Consider gitignoring runtime directories

---

### 7. DOCKER COMPOSE FILES

**Status:** 🐳 KEEP - But organize variants

**Current Root Files:**
- `docker-compose.yml` (26KB) - **KEEP at root** (main compose file)
- `docker-compose.cpu.yml` (546B) - Move to `deploy/compose/`
- `docker-compose.cuda.yml` (5KB) - Move to `deploy/compose/`
- `docker-compose.plugins.yml` (6KB) - Move to `deploy/compose/`
- `docker-compose-copilot.yml` (17KB) - Move to `deploy/compose/`

**Reference Analysis:**
- README.md references compose files with root-relative paths: `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up`
- All references must be updated atomically if files are moved

**Recommendation:** Keep main `docker-compose.yml` at root, organize variants in `deploy/compose/` with updated README references

---

### 8. CONFIG FILES

**Status:** ⚙️ REVIEW - Keep for now, future migration

**Root Config Files:**
- `.env.example` (11KB) - **KEEP** (template for environment setup)
- `.env.cuda` - Specialized CUDA environment (move to `config/env/`)
- `.env.local.example` - **KEEP** (local development template)
- `.env.production.plugins` - Production plugin config (move to `config/env/`)

**Recommendation:** Keep examples at root, move specialized configs to `config/env/`

---

### 9. DATA & STATE FILES

**Status:** 💾 AUDIT - Runtime state shouldn't be in git

**Problematic Files:**
- `data/automation_jobs.json` - Empty runtime state
- `auth.db`, `auth_sessions.db` - Empty database files (0 bytes)
- `model_registry.json` (1.7KB) - Duplicate of `models/llm_registry.json` and `server/model_registry.json`
- `models/llm_registry.json` (9.8KB) - Model registry
- `models/llm_registry.json.backup` (5.2KB) - Backup file

**Recommendation:** 
- Remove empty database files
- Consolidate model registries to single canonical location
- Gitignore runtime data directories

---

### 10. RUNTIME DIRECTORIES

**Status:** 🗂️ GITIGNORE - Should not be in repository root

**Directories to Gitignore:**
- `__pycache__/` - Python bytecode
- `logs/` - Application logs
- `cache/` - Runtime cache
- `backups/` - Database backups  
- `model_cache/` - Model cache
- `benchmarks/` - Benchmark results (unless part of test suite)

**Recommendation:** Add to `.gitignore` if not already present

---

## Risk Assessment

### HIGH RISK (Requires careful migration)
1. **Root `server/` directory** - Contains valuable extension system, must migrate before deletion
2. **Docker Compose variants** - Referenced in README, requires atomic updates
3. **`.env.local`** - Committed to git, may contain secrets (currently empty)

### MEDIUM RISK (Requires validation)  
1. **Utility scripts** - May be used by CI/CD or developers
2. **Setup directory** - May be used by build processes
3. **Config files** - May be referenced by deployment scripts

### LOW RISK (Safe to clean up)
1. **Documentation files** - Pure information, no runtime impact
2. **PDF files** - Generated artifacts, can be regenerated
3. **Suspicious files** - Empty files, accidental commits
4. **Runtime directories** - Should be gitignored anyway

---

## Migration Strategy

### Phase 1: Safe Classification & Planning ✅ COMPLETE
- [x] Inventory all root entries
- [x] Audit server directory imports/references  
- [x] Compare extension implementations
- [x] Classify all artifacts by risk and value
- [x] Create this comprehensive report

### Phase 2: Preserve High-Value Extension Code
1. Create `src/ai_karen_engine/extensions/rbac/` directory
2. Migrate `extension_permissions.py` → `extensions/rbac/permissions.py`
3. Migrate `extension_rbac.py` → `extensions/rbac/manager.py`
4. Enhance canonical `extensions/health.py` with root `extension_health_monitor.py` features
5. Integrate config validation from `extension_config_validator.py`
6. Update imports in `start.py` to use canonical paths
7. Test extension system functionality

### Phase 3: Safe Moves (Low Risk)
1. Move documentation to organized `docs/` structure
2. Move scripts to `scripts/{admin,diagnostics,migrations,models,deploy,dev}/`
3. Move test files to proper `tests/` locations
4. Move Docker Compose variants to `deploy/compose/`
5. Update all references (README, scripts, docs)

### Phase 4: Cleanup & Deletion
1. Delete obvious garbage files (`.codex`, empty databases, etc.)
2. Archive/delete historical reports  
3. Delete generated PDFs
4. Gitignore runtime directories
5. Delete `scratch/`, `setup/` (if unused)
6. **DELETE root `server/`** (only after Phase 2 complete)

### Phase 5: Validation
1. Run full test suite: `pytest tests/ -q`
2. Check imports: `python -m compileall src`
3. Validate Docker Compose: `docker compose config`
4. Verify all scripts still work
5. Check documentation links

---

## Immediate Actions Required

1. **DO NOT DELETE** root `server/` - it contains valuable extension code
2. **Audit** `.env.local` for secrets (currently appears safe)
3. **Investigate** `head_version.txt` and `.codex` before deletion
4. **Plan** extension system migration before any server deletion
5. **Update** `.gitignore` to prevent future runtime state commits

---

## Success Criteria

- [ ] Single canonical server authority at `src/ai_karen_engine/server/`
- [ ] All high-value extension code migrated and tested
- [ ] Documentation organized in proper `docs/` hierarchy  
- [ ] Scripts organized in functional `scripts/` subdirectories
- [ ] No runtime state committed to git
- [ ] No suspicious/garbage files at root
- [ ] All imports and references updated
- [ ] Full test suite passes
- [ ] Docker Compose files validated
- [ ] Clean, professional repository root

---

## Next Steps

**Immediate:** Review this report and approve Phase 2 (extension migration) plan

**Short-term:** Execute Phase 2 to preserve valuable extension code

**Medium-term:** Complete Phases 3-4 for safe cleanup

**Long-term:** Establish repository hygiene practices to prevent future clutter

---

**Report prepared for:** ROOT-CLEANUP-1A sprint  
**Next phase:** EXTENSION-KERNEL-1 (reuse and migrate valuable extension code)  
**Final phase:** ROOT-CLEANUP-1B (delete duplicate authority and normalize root)
# AI-Karen: Production AI Platform
[![CI](https://github.com/OWNER/AI-Karen/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/AI-Karen/actions/workflows/ci.yml)

> **Enterprise-ready AI platform with modular architecture, multi-database support, and comprehensive UI ecosystem.**
> AI-Karen provides a production-grade FastAPI backend with multiple frontend interfaces, extensive plugin system, and robust data infrastructure for scalable AI applications.

AI-Karen is a comprehensive, production-ready AI platform designed for enterprise deployments. The system features a modular architecture with FastAPI backend, multiple UI interfaces, extensive plugin ecosystem, and robust multi-database infrastructure optimized for AI workloads.

### LLM Runtime: In‑Process by Default

This project defaults to the in‑process llama‑cpp‑python runtime for local GGUF models. The legacy external Llama.cpp server manager (`serverKent/`) has been removed to simplify operations and reduce latency.

- Place GGUF models under `models/llama-cpp/` (e.g., `Phi-3-mini-4k-instruct-q4.gguf`).
- Default settings point to this model; adjust `llm_settings.json` if needed.
- No HTTP llama server is required — the API performs inference directly.

Optional: If you must run an external `llama-server`, do it outside this repo and point a custom provider to it; in-repo support is intentionally not maintained.

### Startup Warmup

On boot, the backend preloads the default llama‑cpp model (best‑effort) to avoid first‑request latency. Control via `WARMUP_LLM` env (`true` by default).

### Performance Profile (OpenBLAS)

For CPU speedups, a “perf” image variant enables OpenBLAS for llama‑cpp:

- Build: `PROFILE=runtime-perf docker compose build api` (or set `PROFILE=runtime-perf` in your environment).
- Default remains `runtime` (portable, no BLAS). Both variants support in‑process inference.

Tuning env:

- `LLAMA_THREADS`: override CPU threads (default: `os.cpu_count()`).
- `LLAMA_MLOCK`: set `true` to lock model in RAM (requires sufficient memory).
- `n_gpu_layers` in `llm_settings.json`: offload layers to GPU when configured.

---

## Overview

**Core Platform Features:**
* **KIRE-KRO Intelligence** - Production LLM routing with intent classification, dynamic suggestions, and graceful degradation
* **NeuroVault Memory** - Tri-partite memory system with biological decay functions and hybrid retrieval (R = S × I × D + A)
* **FastAPI Backend** - Production-grade REST API with comprehensive endpoint coverage (106+ endpoints)
* **Multi-Database Architecture** - PostgreSQL, Redis, DuckDB, Milvus, and Elasticsearch integration
* **Performance Optimization** - Dual startup modes with lazy loading, 99%+ faster startup, and 50%+ memory reduction
* **Plugin Ecosystem** - 24+ plugins with hot-reload capability and marketplace integration
* **Extension System** - Modular extensions for analytics, automation, and workflow building
* **Multiple UI Interfaces** - Web (Next.js) is the default interface alongside the Desktop (Tauri) client
* **AI/ML Integration** - HuggingFace Transformers, OpenAI API, local LLM support, CUDA acceleration, helper models
* **Production Monitoring** - Prometheus metrics, OSIRIS logging, health checks, and comprehensive observability
* **Authentication & Security** - Enhanced JWT-based auth with username/email login, advanced validation, rate limiting, password policies, and comprehensive security logging
* **Container Orchestration** - Docker Compose setup with service discovery and health monitoring

**Technology Stack:**
* **Backend**: FastAPI, Python 3.10+, Pydantic, SQLAlchemy, Alembic
* **Databases**: PostgreSQL 15, Redis 7, Elasticsearch 8.9, Milvus 2.3, DuckDB
* **Frontend**: Next.js 15.2.3, React 18, Tauri 2.5
* **AI/ML**: HuggingFace Transformers, llama-cpp-python, scikit-learn 1.5, spaCy 3.7
* **Infrastructure**: Docker, Prometheus, nginx (optional), Kubernetes support

**🚀 Quick Note on Performance**: AI-Karen ships a single Python launcher, `start.py`, plus Docker Compose for full-stack startup. Use the Docker path for the full infrastructure stack, and use `start.py` when you want to run the server directly on the host with external services already available.

---

## 🎯 Recent Updates

### v2.2.0 - Observability Convergence (Latest)

AI-Karen observability has been refactored into a deliberate, lightweight layer:

- **Prometheus** is now the canonical numeric metrics backend
- **Grafana** is optional and moved behind the `observability` Compose profile
- New metrics added for ML inference, personalization, adaptive runtime, memory, agents, tools, and database health
- Prometheus/Grafana images are pinned to validated versions
- Grafana admin password no longer has an insecure default
- Alert rules expanded for runtime, database, ML, and agent/tool failures

**Quick start with observability:**
```bash
docker compose --profile observability up
```

**CPU-only mode:**
```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up
```

**WSL2 NVIDIA setup:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_wsl2_nvidia.ps1
```

### v2.1.0 - Enhanced Authentication & Validation System

AI-Karen now features a comprehensive enhanced authentication and validation system with username-based login, advanced security features, and configurable validation rules.

#### **Enhanced Authentication System**
Production-ready authentication with advanced security and flexibility:

- **Username/Email Login** - Users can authenticate with either username or email address
- **Advanced Form Validation** - Configurable validation rules with detailed error messages
- **Enhanced Security Logging** - Comprehensive audit trail with security event tracking
- **Rate Limiting** - Configurable rate limiting to prevent brute force attacks
- **Password Policies** - Enforced password strength requirements with history tracking
- **Database Migration System** - Proper schema versioning and migration tracking
- **Enhanced Monitoring** - Detailed authentication statistics and security metrics

**Key Features:**
- Flexible login identifiers (username or email)
- Pydantic model validation with detailed error responses
- Security event logging with risk scoring
- Configurable password policies per tenant
- Rate limiting with configurable windows
- Password history tracking to prevent reuse
- Enhanced statistics and monitoring views

**Migration Applied:**
```bash
# The enhanced authentication migration has been applied
# Schema version: 022_enhanced_auth_validation_system.sql
# Username column added to auth_users table
# Enhanced validation and security features enabled
```

**API Usage:**
```bash
# Login with username
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'

# Login with email
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@karen.ai", "password": "<your-password>"}'

# Get enhanced authentication statistics
curl -X GET "http://localhost:8000/api/auth/status"
```

### v2.0.0 - Production AI Intelligence & Memory Systems

AI-Karen has been significantly enhanced with production-grade intelligent routing and neuroscience-inspired memory architecture:

#### **KIRE-KRO System** - Intelligent LLM Routing & Orchestration
The new KIRE-KRO system provides enterprise-grade AI request processing:

- **KIRE Router** - Intelligent LLM selection based on user profiles, task complexity, and provider health
- **KRO Orchestrator** - Prompt-first controller with intent classification, planning, and graceful degradation
- **Helper Models** - TinyLlama scaffolding, DistilBERT classification, spaCy NLP integration
- **Dynamic Suggestions** - Context-aware prompt suggestions for novice/intermediate/expert users
- **Graceful Degradation** - Multi-tier fallback with hardcoded responses when all LLMs fail
- **CUDA Acceleration** - GPU offloading for supported operations (3-5x speedup)
- **OSIRIS Logging** - Comprehensive observability with structured telemetry
- **RBAC & Rate Limiting** - Enterprise security and quota enforcement

**Initialize the KIRE-KRO system:**
```bash
python -m ai_karen_engine.initialize_kire_kro
```

**API Usage:**
```python
from ai_karen_engine.core import process_request

response = await process_request(
    user_input="Explain quantum computing",
    user_id="user123",
)
print(response["message"])
print(response["suggestions"])
```

#### **NeuroVault** - Tri-Partite Memory System
Neuroscience-inspired memory architecture with biological decay functions:

- **Episodic Memory** - Recent experiences (λ=0.12/hour, half-life 5.8h)
- **Semantic Memory** - Long-term facts (λ=0.04/hour, half-life 17.3h)
- **Procedural Memory** - Tool usage patterns (λ=0.02/hour, half-life 34.7h)
- **Hybrid Retrieval** - R = (S × I × D) + A formula with semantic similarity, importance, decay, and access frequency
- **Memory Consolidation** - Automatic episodic → semantic reflection after 24h
- **RBAC & Tenant Isolation** - Multi-tenant memory segregation
- **PII Protection** - Automatic scrubbing of email, phone, SSN, credit cards
- **Background Tasks** - Automated consolidation (6h) and decay (12h) cycles

**API Usage:**
```python
from ai_karen_engine.core.neuro_vault import NeuroVault, MemoryType

vault = NeuroVault()
await vault.store_memory(
    memory_type=MemoryType.EPISODIC,
    content="User asked about quantum computing",
    importance_score=7,
)

memories = await vault.retrieve_memories(query="quantum", k=5)
```

#### **Critical Fixes** - Memory & LLM Integration Stability
Enhanced error handling and diagnostics throughout the AI stack:

- **Enhanced Error Logging** - Registry status, model availability, and detailed failure context
- **Graceful Degradation** - Chat continues even when LLM providers or memory systems fail
- **Contextual Troubleshooting** - Actionable guidance in fallback responses
- **Memory System Robustness** - Proper error handling in extraction, storage, and retrieval
- **Model Registry Validation** - Initialization checks ensure at least one working LLM

**Documentation:**
- [KIRE-KRO System Guide](docs/KIRE_KRO_SYSTEM.md)
- [NeuroVault Memory Architecture](docs/NEUROVAULT_MEMORY_SYSTEM.md)

---

## Quick Start

### Prerequisites

* Python 3.10+
* Docker and Docker Compose

### Installation

```bash
git clone https://github.com/OWNER/AI-Karen.git
cd AI-Karen
pip install -r requirements.txt
```

### Launch Services

```bash
# start the full default stack, including the built-in vLLM service
docker compose up

# start with observability stack (Prometheus + Grafana)
docker compose --profile observability up

# CPU-only mode (WSL2 without NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up

# initialize core tables and default admin user
python create_tables.py
python create_admin_user.py  # follow prompts
```

`docker compose up` starts the core platform without waiting on the optional vLLM image. If you also want the built-in vLLM service, start it separately with `docker compose --profile vllm up -d vllm`.

The default compose stack includes:

- PostgreSQL
- Redis
- Elasticsearch
- Milvus
- the FastAPI API
- the Next.js UI
- the built-in `vllm` service when launched with `--profile vllm`

Observability services are **opt-in** via the `observability` profile:

- Prometheus
- Grafana

```bash
docker compose --profile observability up
```

Optional services remain optional and are still launched by profile when you need them:

```bash
docker compose --profile ollama up
docker compose --profile local-gguf up
```

For CUDA-specific local model support, use the CUDA compose overlay instead:

```bash
docker compose -f docker-compose.yml -f docker-compose.cuda.yml up
```

That path keeps the same built-in `vllm` provider identity and also enables the CUDA-local GGUF service defined in `docker-compose.cuda.yml`.

To start the built-in vLLM service itself, add the profile explicitly:

```bash
docker compose --profile vllm up -d vllm
```

That `vllm` profile is the CUDA path. It requires the host NVIDIA driver and
Docker GPU runtime to be working. The host must pass both checks before vLLM can
initialize CUDA:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

If `nvidia-smi` fails with a driver communication error and `/dev/nvidia*` is
missing, repair the host device nodes and Docker GPU runtime first:

```bash
sudo chown root:root /usr/bin/nvidia-modprobe
sudo chmod 4755 /usr/bin/nvidia-modprobe
sudo nvidia-modprobe -u -c=0
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

If `sudo` itself reports that `/etc/sudo.conf` is not owned by root, repair that
from a real root shell or recovery/admin session before running the CUDA repair:

```bash
chown root:root /etc/sudo.conf
```

The repo also provides a CPU-only vLLM fallback profile. It uses the same
`http://vllm:8000/v1` network alias as the CUDA service, so the API wiring does
not change. Do not run `vllm` and `vllm-cpu` at the same time because they share
the same host port and network alias.

```bash
docker compose --profile vllm-cpu up -d vllm-cpu
```

The default `VLLM_IMAGE` is pinned to `vllm/vllm-openai:v0.6.6` because that image uses an older CUDA runtime that is a better fit for consumer Turing cards such as the RTX 2080 Super. You can still override it when the host driver is new enough:

```bash
VLLM_IMAGE=vllm/vllm-openai:latest docker compose --profile vllm up -d vllm
```

If the host driver is older than the vLLM image expects, you can try:

```bash
VLLM_ENABLE_CUDA_COMPATIBILITY=1 docker compose --profile vllm up -d vllm
```

vLLM documents this compatibility mode for some older-driver systems, but it is not a substitute for a working NVIDIA driver and is only supported on select professional/datacenter GPUs. For GeForce cards, use a compatible driver/image pair instead.

For cards like the RTX 2080 Super, keep `KAREN_BUILTIN_VLLM_DTYPE=float16` so vLLM does not try to use `bfloat16` and then fall back at startup.

If Docker cannot reach Docker Hub during the pull, the app itself can still start. The backend will route to Ollama first when available, then Transformers, then the deterministic fallback response. vLLM becomes an additional runtime once its image finishes downloading and the container becomes healthy.

#### Ollama Options

For Docker installs, the default and more robust path is to let the `api` container reach an Ollama instance already running on the host machine:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

That keeps one local Ollama runtime on the user machine and avoids making the optional compose-side Ollama service a hidden requirement.

If you want Ollama fully inside the compose stack instead, start the optional `ollama` service:

```bash
docker compose --profile ollama up -d
```

Then point the API at the in-network service:

```bash
OLLAMA_BASE_URL=http://ollama:11434
```

Summary:
- Host Ollama: recommended default when the user already has Ollama running locally.
- In-stack Ollama: optional compose profile named `ollama`, on the same Docker network as `api`.

If host Ollama is installed but Karen still reports that the API container cannot reach it, the usual cause on Linux is that Ollama is bound only to `127.0.0.1:11434`. The Docker container cannot reach the host through loopback-only binding.

Use this systemd override on the host to expose Ollama on the host gateway interface:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/10-host-access.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Verify both host and container reachability after the restart:

```bash
ss -ltnp | grep 11434
curl http://127.0.0.1:11434/api/tags
docker compose exec -T api curl http://host.docker.internal:11434/api/tags
```

Expected result:
- The Ollama listener must not be loopback-only.
- The API container must be able to reach `http://host.docker.internal:11434/api/tags`.

Windows note:
- Docker Desktop already supports `host.docker.internal`.
- No extra systemd step is required, but Ollama still needs to be reachable from the host gateway path.

### Non-Docker Launch

Use `start.py` when you want to run the FastAPI server directly on the host.

```bash
python start.py
```

That launcher starts the server process only. Any external systems you want AI-Karen to use still need to be running somewhere reachable:

- PostgreSQL
- Redis
- Elasticsearch
- Milvus
- Ollama, if you want host Ollama fallback
- vLLM, if you want the `builtin_vllm` runtime path outside Docker

For CUDA-capable local runs, keep the same launcher and point the server at CUDA-ready services and models through environment variables:

```bash
CUDA_VISIBLE_DEVICES=0 \
KAREN_BUILTIN_VLLM_ENABLED=true \
KAREN_BUILTIN_VLLM_BASE_URL=http://localhost:8001/v1 \
KAREN_BUILTIN_VLLM_HEALTH_URL=http://localhost:8001/health \
python start.py
```

If you are using local GGUF or Transformers-backed paths on a CUDA box, set the corresponding runtime variables in `.env` before starting `start.py`.

The repo also includes `.env.cuda` for shell-based CUDA runs. Source it before `python start.py` if you want the built-in vLLM runtime to target CUDA endpoints outside Docker.

### WSL2 NVIDIA GPU Setup

For WSL2 hosts, AI-Karen provides automated NVIDIA Container Toolkit setup scripts:

**From Windows PowerShell (Administrator):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_wsl2_nvidia.ps1
```

**From inside WSL2 (Ubuntu/Debian):**
```bash
sudo bash scripts/setup_wsl2_nvidia.sh
```

After setup, restart WSL2 and Docker Desktop:
```bash
wsl --shutdown
```

Verify GPU access:
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### CPU-Only Mode

If you don't have an NVIDIA GPU or want to run without GPU acceleration:

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up
```

The `docker-compose.cpu.yml` override removes all NVIDIA device requirements from services.

## Access URLs

- **Frontend**: http://localhost:8010 (Web UI)
- **API Documentation**: http://localhost:8000/docs
- **Authentication Status**: http://localhost:8000/api/auth/status
- **Health Check**: http://localhost:8000/health
- **API Base**: http://localhost:8000/api
- **Metrics**: http://localhost:8000/metrics
- **Prometheus**: http://localhost:9090 (when observability profile is active)
- **Grafana**: http://localhost:3001 (when observability profile is active)
- **Database**: localhost:5434 (PostgreSQL)

**Default Login Credentials:**
- Username: `admin` or Email: `admin@kari.ai`
- Password: `Admin@123!`
- Password: set via first-run setup or `KARI_ADMIN_PASSWORD`
- **⚠️ Important**: Do not ship a default password in production; rotate immediately if you used a bootstrap value.

**Login Identifier Notes**
- The backend accepts `username` or `email`. For environments that have historical accounts under both `@karen.ai` and `@kari.ai`, login resolution is deterministic:
  - If you log in with `username: "admin"`, the service prefers `admin@karen.ai` when both exist.
  - If you log in with `email: "admin@karen.ai"`, it will also accept the `admin@kari.ai` alias when only that account exists (and vice versa).

## Performance & Optimization

### Resource Management Features

AI-Karen includes a comprehensive optimization system designed for efficient resource usage:

**🔧 Lazy Loading System**
- Services initialize only when first accessed
- Automatic service lifecycle management
- Background resource cleanup
- Memory usage monitoring

**📊 Optimization Profiles**
- **Development**: Full features, immediate availability
- **Production**: Balanced performance and efficiency
- **Minimal**: Essential services only
- **Ultra-Minimal**: Extremely lightweight for containers

**⚡ Performance Improvements**
- **Startup time**: Up to 99%+ faster (0.01s vs 3-5s)
- **Memory usage**: 50%+ reduction in initial footprint  
- **CPU efficiency**: Lower baseline resource consumption
- **Auto-cleanup**: Automatic service shutdown when idle

### Configuration Options

Environment variables for fine-tuning performance:

```bash
# Lazy loading configuration
KARI_LAZY_LOADING=true          # Enable lazy service loading
KARI_MINIMAL_STARTUP=true       # Start only essential services
KARI_ULTRA_MINIMAL=true         # Extreme resource conservation
KARI_RESOURCE_MONITORING=true   # Enable resource monitoring

# Service-specific settings
KARI_DEFER_AI_SERVICES=true     # Defer AI model loading
KARI_DEFER_DATABASE_POOLS=true  # Lazy database connections
KARI_AUTO_CLEANUP=true          # Automatic service cleanup
```

See `config/performance.yml` for detailed optimization settings.

### Run Tests

```bash
pytest
```

## Database Setup

AI-Karen ships with multiple data stores. The default `docker-compose.yml`
spins up the full stack with sensible development defaults:

| Service | Purpose | Port |
|---------|---------|------|
| PostgreSQL | metadata storage | 5433 |
| Redis | caching and sessions | 6379 |
| Milvus | vector similarity search | 19530 |
| Elasticsearch | full-text search | 9200 |
| DuckDB | local analytics | n/a |

Custom connection strings can be supplied via environment variables defined in `config/`.

## Example Usage

Query the health endpoint:

```bash
curl http://localhost:8000/api/health/summary
```

Create a chat completion using the Python client:

```python
import requests

resp = requests.post(
    "http://localhost:8000/api/chat/completions",
    json={"input": "Hello, AI-Karen"},
)
print(resp.json())
```

---

## Authentication Configuration

The authentication service relies on the `AuthConfig` class for all
runtime settings. Configuration can be provided in environment-specific
YAML or JSON files:

```python
from ai_karen_engine.auth.config import AuthConfig

# Load from a specific file and environment
config = AuthConfig.from_file("config/auth_config.yaml", "development")

# Or discover the file in the default ``config/`` directory
config = AuthConfig.from_environment("production")
```

Example configuration files are provided in `config/auth_config.yaml`
and `config/auth_config.json`.

### Enhanced Authentication System

AI-Karen features a comprehensive enhanced authentication system with username/email login, advanced validation, and security features:

**Key Features:**
- **Flexible Login**: Users can authenticate with either username or email
- **Advanced Validation**: Configurable form validation with detailed error messages
- **Security Logging**: Comprehensive audit trail with security event tracking
- **Rate Limiting**: Configurable rate limiting to prevent brute force attacks
- **Password Policies**: Enforced password strength requirements with history tracking
- **Enhanced Monitoring**: Detailed authentication statistics and security metrics

**Migration Status:**
The enhanced authentication migration (v022) has been applied, adding:
- Username column to auth_users table
- Enhanced validation and security features
- Comprehensive monitoring and statistics

**Authentication Examples:**

```bash
# Login with username
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'

# Login with email  
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@karen.ai", "password": "<your-password>"}'

# Get authentication status and statistics
curl -X GET "http://localhost:8000/api/auth/status"
```

**Default Credentials:**
- Username: `admin` or Email: `admin@karen.ai`
- Password: set via first-run setup or `KARI_ADMIN_PASSWORD`
- **Important**: Rotate/replace any bootstrap password after first login

**Migration Documentation:**
See [Enhanced Authentication Migration Guide](ENHANCED_AUTH_MIGRATION_README.md) for detailed migration information and new features.

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend Layer                           │
├─────────────────┬─────────────────┤
│   Web UI        │  Desktop UI     │
│  (Next.js)      │   (Tauri)       │
│  Port: 9002     │  Native App     │
└─────────────────┴─────────────────┘
                               │
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                             │
│                      Port: 8000                                 │
├─────────────────────────────────────────────────────────────────┤
│  • REST API (106+ endpoints)    • Plugin System (24+ plugins)  │
│  • Authentication & RBAC        • Extension System             │
│  • Multi-tenant Support         • Health Monitoring            │
│  • Prometheus Metrics           • Event Bus                    │
└─────────────────────────────────────────────────────────────────┘
                               │
┌─────────────────────────────────────────────────────────────────┐
│                    Database Layer                               │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────┤
│ PostgreSQL  │   Redis     │   Milvus    │ Elasticsearch│ DuckDB  │
│ Port: 5433  │ Port: 6379  │Port: 19530  │ Port: 9200   │ Local   │
│ (Metadata)  │ (Cache)     │ (Vectors)   │ (Search)     │(Analytics)│
└─────────────┴─────────────┴─────────────┴─────────────┴─────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Observability Layer                          │
│              Profile: observability (opt-in)                    │
├─────────────────────────────────────────────────────────────────┤
│  • Prometheus (metrics)       • Grafana (dashboards)           │
│  • Alert Rules                • Health Metrics                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Architectural Principles

1. **Modular Design** - Loosely coupled components with clear interfaces
2. **Horizontal Scalability** - Database services can be scaled independently
3. **Plugin Architecture** - Hot-reloadable plugins with manifest-based configuration
4. **Multi-UI Support** - Different interfaces for different use cases
5. **Production Ready** - Comprehensive monitoring, logging, and health checks

---


## Development Setup

### Local Development Environment

```bash
# Install development dependencies
pip install -e .
pip install -r requirements.txt

# Install pre-commit hooks
pre-commit install

# Set environment variables
export POSTGRES_USER=karen_user
export POSTGRES_PASSWORD=karen_secure_pass_change_me
export POSTGRES_DB=ai_karen
export POSTGRES_HOST=postgres  # use 'postgres' when running via Docker
export POSTGRES_PORT=5433  # change if port 5432 is busy
export REDIS_URL=redis://localhost:6379/0
export ELASTICSEARCH_URL=http://localhost:9200
export MILVUS_HOST=localhost
export MILVUS_PORT=19530
```

### Observability Development

When developing metrics locally, ensure `prometheus_client` is installed:

```bash
pip install prometheus_client
```

The metrics system uses a safe registration pattern to avoid duplicate metric errors. New metrics should be registered through `ai_karen_engine.core.observability.metrics.MetricsManager`.

### Development Commands

| Task | Command |
|------|---------|
| Format code | `black .` |
| Type checking | `mypy .` |
| Linting | `ruff check .` |
| Run tests | `pytest` |
| Start API | `uvicorn main:create_app --factory --reload` |
| Build web UI | `cd ui_launchers/web_ui && npm run build` |
| Build desktop | `cd ui_launchers/desktop_ui && npm run tauri build` |

### Test Environment Setup

The test suite depends on several third-party libraries, including
`httpx`, `sqlalchemy`, `asyncpg`, `aiohttp`, `psutil`,
`prometheus_client`, and `bcrypt`. Install all test dependencies
before running `pytest`:

```bash
pip install -r requirements.txt
```

### Demo Scripts

When running the example demo scripts directly from the repository, set
`PYTHONPATH=src` so the `ai_karen_engine` package can be imported without
modifying `sys.path` inside the scripts:

```bash
PYTHONPATH=src python demo_plugin_system.py
```

### Plugin Development

Create a new plugin in `src/ai_karen_engine/plugins/`:

```bash
mkdir src/ai_karen_engine/plugins/my_plugin
```

**plugin_manifest.json:**
```json
{
  "name": "my_plugin",
  "description": "My custom plugin",
  "plugin_api_version": "0.1.0",
  "required_roles": ["user"],
  "intent": ["my_intent"]
}
```

**handler.py:**
```python
def run(message, context):
    return {
        "intent": "my_intent",
        "confidence": 1.0,
        "response": f"Hello from my_plugin! Message: {message}"
    }
```

Plugins are automatically discovered and hot-reloaded.

---

## Production Deployment

### Docker Compose (Recommended)

```bash
# Production deployment
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# With custom environment
cp .env.example .env
# Edit .env with production values
docker compose --env-file .env up -d

# With observability stack
docker compose --profile observability up -d
```

### Kubernetes Deployment

```bash
# Using Helm chart
helm install ai-karen ./charts/kari/ \
  --set image.tag=latest \
  --set postgresql.enabled=true \
  --set redis.enabled=true
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_USER` | PostgreSQL user | `karen_user` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `karen_secure_pass_change_me` |
| `POSTGRES_DB` | PostgreSQL database | `ai_karen` |
| `POSTGRES_HOST` | PostgreSQL host | `postgres` |
| `POSTGRES_PORT` | PostgreSQL port | `5433` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `ELASTICSEARCH_URL` | Elasticsearch URL | `http://localhost:9200` |
| `MILVUS_HOST` | Milvus host | `localhost` |
| `MILVUS_PORT` | Milvus port | `19530` |
| `JWT_SECRET_KEY` | JWT signing key | `your-secret-key` |
| `ENABLE_SELF_REFACTOR` | Enable self-refactoring | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `KARI_CORS_ORIGINS` | Comma-separated list of allowed CORS origins | `*` |
| `KARI_CORS_METHODS` | Allowed CORS HTTP methods (comma-separated or `*`) | `*` |
| `KARI_CORS_HEADERS` | Allowed CORS request headers (comma-separated or `*`) | `*` |
| `KARI_CORS_CREDENTIALS` | Whether to allow credentials in CORS requests | `true` |
| `KARI_ECO_MODE` | Skip heavy NLP model loading | `false` |
| `KARI_MEMORY_SURPRISE_THRESHOLD` | Novelty threshold for storing memory | `0.85` |
| `KARI_DISABLE_MEMORY_SURPRISE_FILTER` | Disable surprise filtering to store all memories | `false` |
| `USE_GPU` | Enable GPU acceleration (requires WSL2 NVIDIA setup) | `true` |
| `PROMETHEUS_IMAGE` | Prometheus Docker image | `prom/prometheus:v2.47.0` |
| `GRAFANA_IMAGE` | Grafana Docker image | `grafana/grafana:9.5.2` |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password (must be set explicitly) | — |

---

## API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | System health check |
| `GET` | `/ready` | Readiness probe |
| `GET` | `/metrics` | Application metrics |
| `GET` | `/metrics/prometheus` | Prometheus metrics |
| `POST` | `/chat` | Chat completion |
| `POST` | `/store` | Store memory |
| `POST` | `/search` | Search memories |
| `GET` | `/plugins` | List plugins |
| `GET` | `/models` | List AI models |

The memory query endpoint (`/api/memory/query`) returns at most **100 results** by default.
You can override this cap by providing the `result_limit` parameter in your request.

### Tenant Header

Most API endpoints are tenant-aware. Include an `X-Tenant-ID` header with your
tenant name in requests that are not listed under the public paths. For local
testing you can use `default`:

```bash
curl -H "X-Tenant-ID: default" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"text": "hello"}' http://localhost:8000/chat
```

### Authentication

```bash
# Login with username (new feature)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'

# Login with email (traditional method)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@karen.ai", "password": "<your-password>"}'

# Use token for authenticated requests
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/chat

# Get current user information
curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <token>"

# Get authentication statistics (admin only)
curl -X GET http://localhost:8000/api/auth/stats \
  -H "Authorization: Bearer <token>"
```

### Enhanced Validation System

The new validation system provides comprehensive form validation with detailed error messages:

```bash
# Test login validation - missing identifier (should fail)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "<your-password>"}'
# Returns: "Either email or username must be provided"

# Test with invalid email format (should fail)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "invalid-email", "password": "<your-password>"}'

# Test with valid username (should succeed)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'
```

**Validation Features:**
- **Form Validation**: Login, registration, and password reset forms
- **Field Validation**: Email format, username patterns, password strength
- **Security Validation**: SQL injection prevention, XSS protection
- **Detailed Errors**: Specific error messages for each validation failure
- **Configurable Rules**: Database-stored validation rules for flexibility

### Plugin Management

```bash
# List plugins
curl http://localhost:8000/plugins

# Enable plugin
curl -X POST http://localhost:8000/plugins/my_plugin/enable

# Reload plugins
curl -X POST http://localhost:8000/plugins/reload
```

---

## Monitoring & Observability

### Observability Stack

AI-Karen includes a complete observability stack that is **optional by default**:

```bash
# Start only the minimal runtime
docker compose up

# Start with observability stack (Prometheus + Grafana)
docker compose --profile observability up
```

**Observability components:**
- **Prometheus** (`v2.47.0`) — Canonical numeric metrics backend
- **Grafana** (`9.5.2`) — Optional dashboards and operations UI

**Key URLs (when observability profile is active):**
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001

**Grafana credentials:**
- Set `GRAFANA_ADMIN_PASSWORD` in `.env` (no default password for security)
- Provisioned with Prometheus datasource and health dashboards

### Metrics

The system exposes comprehensive Prometheus metrics at `/metrics`:

**Runtime metrics:**
- `karen_requests_total` — Total HTTP requests by method, endpoint, status
- `karen_request_duration_seconds` — Request latency histogram
- `karen_requests_inflight` — Current in-flight requests
- `karen_degraded_requests_total` — Requests served in degraded mode

**ML/Intelligence metrics:**
- `karen_ml_inference_seconds` — ML inference latency by task, model, status
- `karen_ml_predictions_total` — Total ML predictions
- `karen_ml_fallback_total` — ML fallback events
- `karen_ml_model_load_failures_total` — Model load failures
- `karen_ml_shadow_disagreement_total` — Shadow model disagreements

**Personalization metrics:**
- `karen_personalization_evidence_total` — Personalization evidence events
- `karen_personalization_updates_total` — Model updates
- `karen_personalization_contradictions_total` — Contradictions detected
- `karen_personalization_snapshot_seconds` — Snapshot build latency

**Adaptive intelligence metrics:**
- `karen_adaptive_recommendations_total` — Adaptive recommendations
- `karen_adaptive_ranking_seconds` — Ranking latency
- `karen_adaptive_candidate_count` — Candidates considered
- `karen_adaptive_shadow_disagreement_total` — Shadow disagreements
- `karen_suggestions_total` — Suggestions emitted

**Database/Redis metrics:**
- `karen_postgres_health` — PostgreSQL health status
- `karen_redis_health` — Redis health status
- `karen_db_query_seconds` — Database query latency
- `karen_queue_depth` — Internal queue depth

**Agent/Tool metrics:**
- `karen_agent_execution_total` — Agent executions by status
- `karen_agent_execution_seconds` — Agent execution latency
- `karen_tool_execution_total` — Tool executions by status

**Model orchestrator metrics:**
- `kari_model_operations_total` — Model operations
- `kari_model_operation_duration_seconds` — Operation duration
- `kari_model_download_bytes_total` — Download throughput
- `kari_model_storage_usage_bytes` — Storage usage

### Health Checks

```bash
# Verify backend is listening on port 8000
ss -ltnp | grep :8000 || lsof -iTCP:8000 -sTCP:LISTEN

# System health
curl http://localhost:8000/health

# API health
curl http://localhost:8000/api/health

# Detailed health summary
curl http://localhost:8000/api/health/summary

# Metrics
curl http://localhost:8000/metrics

# Service-specific health
curl http://localhost:8000/api/services/postgres/health
```

---

## Troubleshooting

### Quick Fixes

For immediate solutions to common issues:
- **[Environment Setup Fix](docs/quick-fixes/ENVIRONMENT_SETUP_FIX.md)** - Resolve Docker Compose warnings
- **[Connection Issues Checklist](docs/quick-fixes/CONNECTION_ISSUES_CHECKLIST.md)** - Fix port 8001 connection errors
- **[CORS Issues Fix](docs/troubleshooting/CORS_ISSUES_FIX.md)** - Resolve cross-origin request blocked errors
- **[Port 8001 Connection Issue](docs/troubleshooting/PORT_8001_CONNECTION_ISSUE.md)** - Specific fix for frontend connection problems

### Automated Fix Scripts

Run these scripts to automatically diagnose and fix common issues:
```bash
# Fix environment variables and Docker Compose warnings
./fix-connection-issue.sh

# Fix CORS issues specifically
./fix-cors-issue.sh

# Comprehensive frontend-backend connection fix
./fix-frontend-backend-connection.sh
```

### Common Issues

#### WSL2 NVIDIA GPU Setup

**Problem**: `nvidia-container-cli: initialization error: WSL environment detected but no adapters were found`

**Solution**: Run the automated WSL2 NVIDIA setup script from Windows PowerShell (Administrator):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_wsl2_nvidia.ps1
```

Or from inside WSL2 (Ubuntu/Debian):

```bash
sudo bash scripts/setup_wsl2_nvidia.sh
```

Then restart WSL2 and Docker Desktop:

```bash
wsl --shutdown
```

Verify the setup:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### CPU-Only Mode

If you don't have an NVIDIA GPU or want to run without GPU acceleration:

```bash
# CPU-only mode (no GPU requirements)
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up
```

The `docker-compose.cpu.yml` override removes all NVIDIA device requirements from services.

#### Authentication Issues

**Problem**: Login failures or "Invalid credentials" errors

**Solution**:
```bash
# Check authentication service status
curl http://localhost:8000/api/auth/status

# Verify default credentials work
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'

# Check authentication statistics
curl http://localhost:8000/api/auth/status | jq .stats

# If migration issues, check schema version
docker compose exec postgres psql -U karen_user -d ai_karen -c \
  "SELECT migration_name, status FROM migration_history ORDER BY applied_at DESC LIMIT 5;"
```

#### Schema Migration Issues

**Problem**: Schema version mismatch or migration errors

**Solution**:
```bash
# Check current migration status
docker compose exec postgres psql -U karen_user -d ai_karen -c \
  "SELECT migration_name, applied_at, status FROM migration_history WHERE service = 'postgres' ORDER BY applied_at DESC LIMIT 1;"

# If migration_history table doesn't exist, initialize it
docker compose exec postgres psql -U karen_user -d ai_karen -c \
  "CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) NOT NULL,
    service VARCHAR(50) NOT NULL DEFAULT 'postgres',
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'applied'
  );"

# Record current migration as applied
docker compose exec postgres psql -U karen_user -d ai_karen -c \
  "INSERT INTO migration_history (migration_name, service, status) 
   VALUES ('022_enhanced_auth_validation_system.sql', 'postgres', 'applied')
   ON CONFLICT DO NOTHING;"
```

#### Plugin Loading Failures

**Problem**: Plugins not loading or executing

**Solution**:
```bash
# Validate plugin manifest
python -c "import json; print(json.load(open('src/ai_karen_engine/plugins/my_plugin/plugin_manifest.json')))"

# Reload plugins
curl -X POST http://localhost:8000/plugins/reload

# Check plugin logs
docker compose logs api | grep plugin
```

#### Memory Issues

**Problem**: High memory usage or OOM errors

**Solution**:
```bash
# Check memory usage
docker stats

# Adjust memory limits in docker-compose.yml
# Restart with memory limits
docker compose up -d --force-recreate
```

#### Frontend Build Issues

**Problem**: UI build failures

**Solution**:
```bash
# Clear node modules
cd ui_launchers/web_ui
rm -rf node_modules package-lock.json
npm install

# Check Node.js version
node --version  # Should be 18+
```

### Performance Optimization

1. **Database Tuning**:
   - Adjust PostgreSQL `shared_buffers` and `work_mem`
   - Configure Redis `maxmemory` policy
   - Optimize Elasticsearch heap size

2. **API Performance**:
   - Enable FastAPI response caching
   - Configure connection pooling
   - Use async endpoints where possible

3. **Frontend Optimization**:
   - Enable Next.js production build optimizations
   - Configure CDN for static assets
   - Implement proper caching headers

### Getting Help

1. **Check Documentation**: Review component-specific README files
2. **System Analysis**: Run `python scripts/doc_analysis.py` for system overview
3. **Health Checks**: Use `/api/health/summary` endpoint
4. **Logs**: Check application and service logs
5. **Community**: Submit issues with system analysis output

---

## Contributing

### Development Workflow

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run the full test suite
5. Submit a pull request

### Code Standards

* **Python**: Black formatting, type hints, docstrings
* **JavaScript/TypeScript**: ESLint, Prettier formatting
* **Rust**: Standard rustfmt formatting
* **Documentation**: Update README files for any architectural changes

### Testing

Install project dependencies before running tests:

```bash
pip install -r requirements.txt
```

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/services/
pytest tests/ui/

# Run with coverage
pytest --cov=src/ai_karen_engine
```

---

## License

This project is dual-licensed:
- **Mozilla Public License 2.0** for open source use
- **Commercial License** for enterprise deployments

See [LICENSE.md](LICENSE.md) and [LICENSE-commercial.txt](LICENSE-commercial.txt) for details.

---

## Documentation

### Component Documentation
- [Web UI Documentation](ui_launchers/web_ui/README.md) - Next.js web interface
- [Desktop UI Documentation](ui_launchers/desktop_ui/README.md) - Tauri desktop application
- [Database Documentation](docker/database/README.md) - Multi-database setup
- [Plugin Documentation](plugin_marketplace/README.md) - Plugin development guide
- [Extension Documentation](extensions/README.md) - Extension system overview

### Setup Scripts
- [WSL2 NVIDIA Setup](scripts/README.md) - GPU acceleration setup for WSL2
- [Database Scripts](docker/scripts/README.md) - Database initialization and migration

### Authentication Documentation
- [Enhanced Authentication Migration Guide](ENHANCED_AUTH_MIGRATION_README.md) - Complete migration guide with new features
- [Auth Service](docs/auth/auth_service.md) - Core authentication service overview
- [Auth Service Deployment Guide](docs/auth/auth_service_deployment.md) - Environment setup and configuration loading
- [Auth Service Migration Guide](docs/auth/auth_service_migration.md) - Removal of legacy security modules

### Architecture Guides
- [API Reference](docs/api/api_reference.md) - Complete API documentation
- [Architecture Overview](docs/architecture.md) - System architecture details
- [Development Guide](docs/guides/development_guide.md) - Development best practices
- [Security Framework](docs/security.md) - Security implementation
- [Memory Architecture](docs/memory_arch.md) - Memory system design
- [Plugin Specification](docs/plugins/plugin_spec.md) - Plugin development specification
- [Agent Roadmap](docs/agent_roadmap.md) - Production readiness and feature roadmap for the web UI

### Operational Guides
- [Deployment Guide](docs/guides/deployment.md) - Production deployment
- [Monitoring Guide](docs/guides/observability.md) - Monitoring and observability
- [Troubleshooting Guide](docs/guides/troubleshooting.md) - Common issues and solutions

---

*AI-Karen: Production-ready AI platform for enterprise deployments*

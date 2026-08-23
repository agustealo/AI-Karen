# Karen Scripts Directory

This directory contains utility scripts for Karen's runtime management, auditing, and maintenance.

## Available Scripts

### 🔍 audit_runtime_vllm.sh

**Purpose:** Comprehensive audit of Karen's vLLM runtime integration

**What it does:**
- Verifies vLLM is wired as a real live response engine
- Tests vLLM server endpoints
- Validates provider configuration
- Checks routing logic
- Verifies metadata tracking
- Tests streaming implementation
- Generates detailed audit report

**Usage:**
```bash
# Basic audit
./scripts/audit_runtime_vllm.sh

# With custom configuration
KAREN_VLLM_BASE_URL=http://localhost:8001/v1 \
KAREN_VLLM_MODEL=your-model-name \
KAREN_API_URL=http://localhost:8000 \
./scripts/audit_runtime_vllm.sh
```

**Environment Variables:**
- `KAREN_VLLM_BASE_URL` - vLLM server endpoint (default: `http://localhost:8001/v1`)
- `KAREN_VLLM_HEALTH_URL` - vLLM health endpoint (default: `http://localhost:8001/health`)
- `KAREN_VLLM_MODEL` - Model to test (auto-detected if not set)
- `KAREN_API_URL` - Karen API endpoint (default: `http://localhost:8000`)

**Output:**
- Console output with color-coded results
- Detailed markdown report: `vllm_audit_report_YYYYMMDD_HHMMSS.md`

**Exit Codes:**
- `0` - Audit passed
- `1` - Audit failed (critical issues found)

**Documentation:**
- Quick Start: `docs/VLLM_AUDIT_QUICKSTART.md`
- Full Documentation: `docs/VLLM_RUNTIME_AUDIT.md`
- Executive Summary: `VLLM_AUDIT_SUMMARY.md`

---

### 🚀 setup_wsl2_nvidia.sh / setup_wsl2_nvidia.ps1

**Purpose:** Automated WSL2 NVIDIA Container Toolkit setup for GPU acceleration in Docker

**What it does:**
- Installs NVIDIA Container Toolkit inside WSL2
- Configures Docker runtime for GPU access
- Enables Docker Desktop WSL2 backend
- Verifies `nvidia-smi` and Docker runtime detection

**Usage (Linux/WSL2):**
```bash
sudo bash scripts/setup_wsl2_nvidia.sh
```

**Usage (Windows PowerShell - Administrator):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_wsl2_nvidia.ps1
```

**After setup:**
```bash
wsl --shutdown
# Then restart Docker Desktop
```

**Verify GPU access:**
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

**Prerequisites:**
- NVIDIA GPU with latest Windows driver installed
- WSL2 with a Linux distro (Ubuntu recommended)
- Docker Desktop with WSL2 integration enabled

**Related:**
- CPU-only mode: `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up`

---

## Adding New Scripts

When adding new scripts to this directory:

1. **Make executable:**
    ```bash
    chmod +x scripts/your_script.sh
    ```

2. **Add shebang:**
    ```bash
    #!/usr/bin/env bash
    set -euo pipefail
    ```

3. **Document in this README:**
    - Purpose
    - Usage
    - Environment variables
    - Exit codes

4. **Follow conventions:**
    - Use color codes for output (see audit_runtime_vllm.sh)
    - Generate reports in markdown format
    - Support environment-based configuration
    - Provide helpful error messages

---

## Related Documentation

- **vLLM Audit:** `docs/VLLM_RUNTIME_AUDIT.md`
- **Quick Start:** `docs/VLLM_AUDIT_QUICKSTART.md`
- **Test Suite:** `tests/integration/test_vllm_smoke.py`
- **Summary:** `VLLM_AUDIT_SUMMARY.md`
- **WSL2 NVIDIA Setup:** `scripts/setup_wsl2_nvidia.sh` or `scripts/setup_wsl2_nvidia.ps1`

---

## Support

For issues or questions:
- Review documentation in `docs/`
- Check Karen logs: `logs/karen_api.log`
- Run diagnostics: `./scripts/audit_runtime_vllm.sh`
- WSL2 GPU issues: Run `./scripts/setup_wsl2_nvidia.sh`
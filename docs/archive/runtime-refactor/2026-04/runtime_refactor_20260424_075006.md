# Runtime Authority Refactor Report

Mode: audit
Root: /mnt/Development/KIRO/AI-Karen
Timestamp: 20260424_075006

## Legacy llama.cpp References

/mnt/Development/KIRO/AI-Karen/status.sh:34:if docker ps | grep -q "ai-karen-llamacpp"; then
/mnt/Development/KIRO/AI-Karen/status.sh:43:echo "   Config: $(jq -r '.n_gpu_layers' config/llamacpp/config.json) GPU layers"
/mnt/Development/KIRO/AI-Karen/status.sh:44:echo "   Threads: $(jq -r '.n_threads' config/llamacpp/config.json) CPU threads"
/mnt/Development/KIRO/AI-Karen/status.sh:45:echo "   Context: $(jq -r '.n_ctx' config/llamacpp/config.json) tokens"
/mnt/Development/KIRO/AI-Karen/update-cuda.sh:22:docker-compose -f docker-compose.cuda.yml pull llamacpp-cuda

FAIL: legacy llama.cpp references remain.

## Direct Provider Call Sites

PASS: no direct provider call sites found.

## Runtime Authority

ModelManager: /mnt/Development/KIRO/AI-Karen/src/ai_karen_engine/core/model_runtime/model_manager.py:57:class ModelManager:

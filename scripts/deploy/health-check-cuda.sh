#!/bin/bash

# AI-Karen CUDA Health Check Script
# This script monitors the health of the CUDA-enabled deployment

set -e

echo "🏥 AI-Karen CUDA Health Check"
echo "=================================="

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "❌ Docker is not running"
    exit 1
fi
echo "✅ Docker is running"

# Check if NVIDIA Container Toolkit/CDI is available
if ! docker info | grep -q "cdi.*nvidia"; then
    echo "❌ NVIDIA Container Toolkit/CDI is not available (required for GPU support)"
    echo "   Current deployment: CPU-only mode"
else
    echo "✅ NVIDIA Container Toolkit/CDI is available"
fi

# Check GPU availability
if ! nvidia-smi &> /dev/null; then
    echo "❌ NVIDIA GPU is not available"
    exit 1
fi
echo "✅ GPU is available"

# Check if CUDA services are running (only check if we're in CUDA mode)
if [ "$CUDA_VISIBLE_DEVICES" ]; then
    LABELS=("ai-karen" "local-gguf-cuda")
    CONTAINERS=("ai-karen-app" "ai-karen-local-gguf")
else
    LABELS=("ai-karen")
    CONTAINERS=("ai-karen-app")
fi

for i in "${!CONTAINERS[@]}"; do
    container_name="${CONTAINERS[$i]}"
    service="${LABELS[$i]}"

    if ! docker ps | grep -q "${container_name}"; then
        echo "❌ Service ${service} is not running"
        continue
    fi

    echo "✅ Service ${service} is running"

    # Check health status
    health_status=$(docker inspect --format='{{json .State.Health.Status}}' "${container_name}" 2>/dev/null || echo "not_found")

    if [[ $health_status == *"healthy"* ]]; then
        echo "   🟢 Health: Healthy"
    elif [[ $health_status == *"starting"* ]]; then
        echo "   🟡 Health: Starting"
    else
        echo "   🔴 Health: Not healthy or health check not configured"
    fi

    # Check resource usage
    if docker stats --no-stream "${container_name}" &> /dev/null; then
        echo "   💾 Resource usage:"
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" "${container_name}"
    fi

    echo ""
done

# Check GPU usage
echo "🖥️  GPU Usage:"
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | while read -r gpu_util mem_used mem_total; do
    echo "   GPU: ${gpu_util}% utilization, ${mem_used}MB used / ${mem_total}MB total"
done

# Check model loading
echo ""
echo "📊 Model Loading Status:"
if docker exec ai-karen-local-gguf curl -s http://localhost:8080/health &> /dev/null; then
    echo "✅ local GGUF service is responding"
    
    # Check if model is loaded
    model_info=$(docker exec ai-karen-local-gguf curl -s http://localhost:8080/v1/models 2>/dev/null || echo "not_available")
    if [[ $model_info == *"not_available"* ]]; then
        echo "⚠️  Model endpoint not available"
    else
        echo "✅ Model endpoint is available"
        echo "   Model info: $model_info"
    fi
else
    echo "❌ local GGUF service is not responding"
fi

# Check AI-Karen application
echo ""
echo "🌐 AI-Karen Application Status:"
if curl -s http://localhost:8000/health &> /dev/null; then
    echo "✅ AI-Karen application is responding"
else
    echo "❌ AI-Karen application is not responding"
fi

# Check logs for errors
echo ""
echo "📋 Recent Errors (last 100 lines):"

# Only check Docker Compose logs if in CUDA mode
if [ "$CUDA_VISIBLE_DEVICES" ]; then
    # Set Docker Compose command
    DOCKER_COMPOSE_CMD="${DOCKER_COMPOSE_CMD:-docker compose}"
    if ! command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE_CMD="~/docker-compose"
    fi

    # Check for CUDA-related errors
    echo "   CUDA-related errors:"
    $DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml logs --tail=100 local-gguf-cuda | grep -i "error\|fail\|exception" | head -5 || echo "   No CUDA errors found"

    # Check for general application errors
    echo "   Application errors:"
    $DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml logs --tail=100 ai-karen | grep -i "error\|fail\|exception" | head -5 || echo "   No application errors found"
else
    # CPU-only mode - check AI-Karen logs directly
    echo "   Application errors (CPU mode):"
    echo "   No Docker Compose logs to check - running in CPU-only mode"
fi

echo ""
echo "🎯 Health check completed!"

#!/bin/bash

# AI-Karen CUDA Stop Script
# This script safely stops the CUDA-enabled deployment

set -e

echo "🛑 Stopping AI-Karen CUDA deployment..."

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "❌ Docker is not running"
    exit 1
fi

# Stop the services
echo "📦 Stopping services..."
docker-compose -f docker-compose.cuda.yml down --remove-orphans

# Clean up unused containers and networks
echo "🧹 Cleaning up..."
docker system prune -f

# Remove environment variables
unset CUDA_VISIBLE_DEVICES
unset KARI_LOCAL_GGUF_HOST
unset KARI_LOCAL_GGUF_PORT
unset KARI_LOCAL_GGUF_USE_CUDA

echo "✅ AI-Karen CUDA deployment stopped successfully!"
echo "🚀 To restart: ./deploy-cuda.sh"
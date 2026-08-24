#!/bin/bash

# Update AI-Karen CUDA Deployment Script
# This script updates an existing CUDA deployment

set -e

echo "🔄 Updating AI-Karen CUDA deployment..."

# Check if deployment exists
if [ ! -f "docker-compose.cuda.yml" ]; then
    echo "❌ CUDA deployment not found. Please run ./deploy-cuda.sh first."
    exit 1
fi

# Stop current deployment
echo "🛑 Stopping current deployment..."
./stop-cuda.sh

# Pull latest images
echo "📦 Pulling latest images..."
docker-compose -f docker-compose.cuda.yml pull ai-karen-local-gguf-cuda

# Build updated AI-Karen image
echo "🏗️  Building updated AI-Karen image..."
docker-compose -f docker-compose.cuda.yml build ai-karen

# Start deployment
echo "🚀 Starting updated deployment..."
./deploy-cuda.sh

echo "✅ AI-Karen CUDA deployment updated successfully!"

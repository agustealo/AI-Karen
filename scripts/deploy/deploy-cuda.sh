#!/bin/bash

# AI-Karen CUDA Deployment Script
# This script sets up and deploys AI-Karen with CUDA-enabled local GGUF

set -e

echo "🚀 Starting AI-Karen CUDA deployment..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is available (modern Docker Compose v2)
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose v2 is not available. Please ensure Docker Desktop or Docker Engine with Compose v2 is installed."
    exit 1
fi

# Set Docker Compose command (use modern v2 syntax)
DOCKER_COMPOSE_CMD="docker compose"

# Check if NVIDIA Container Toolkit/CDI is available
if ! docker info | grep -q "cdi.*nvidia"; then
    echo "❌ NVIDIA Container Toolkit/CDI is not available. Please install NVIDIA Container Toolkit."
    echo "   Installation: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    exit 1
fi

# Check if GPU is available
if ! nvidia-smi &> /dev/null; then
    echo "❌ NVIDIA GPU is not available. Please check GPU drivers."
    exit 1
fi

echo "✅ Docker and NVIDIA runtime are properly configured"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p models/local-gguf
mkdir -p logs/local-gguf
mkdir -p config/local-gguf

# Copy configuration files if they don't exist
if [ ! -f config/local-gguf/config.json ]; then
    echo "📋 Copying local GGUF configuration..."
    cp config/local-gguf/config.json config/local-gguf/config.json.backup
fi

# Update local GGUF config to use GPU
echo "⚙️  Updating local GGUF configuration for GPU..."
jq '.n_gpu_layers = -1 | .main_gpu = 0 | .offload_kqv = true | .flash_attn = true' config/local-gguf/config.json > config/local-gguf/config.json.tmp
mv config/local-gguf/config.json.tmp config/local-gguf/config.json

# Set environment variables
export CUDA_VISIBLE_DEVICES=0
export KARI_LOCAL_GGUF_HOST=local-gguf-cuda
export KARI_LOCAL_GGUF_PORT=8080
export KARI_LOCAL_GGUF_USE_CUDA=true

echo "🔧 Environment variables set:"
echo "   CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "   KARI_LOCAL_GGUF_HOST: $KARI_LOCAL_GGUF_HOST"
echo "   KARI_LOCAL_GGUF_PORT: $KARI_LOCAL_GGUF_PORT"
echo "   KARI_LOCAL_GGUF_USE_CUDA: $KARI_LOCAL_GGUF_USE_CUDA"

# Build Docker images
echo "📦 Building Docker images..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml build local-gguf-cuda ai-karen

# Build AI-Karen image
echo "🏗️  Building AI-Karen image..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml build ai-karen

# Stop existing containers if they're running
echo "🛑 Stopping existing containers..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml down --remove-orphans

# Start the services
echo "🚀 Starting services..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 30

# Check service health
echo "🏥 Checking service health..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml ps

# Show logs
echo "📊 Showing logs (last 20 lines)..."
$DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml logs --tail=20

echo "✅ AI-Karen CUDA deployment completed!"
echo "🌐 Access the application at: http://localhost:8000"
echo "📊 Monitor logs: $DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml logs -f"
echo "🛑 Stop services: $DOCKER_COMPOSE_CMD -f docker-compose.cuda.yml down"

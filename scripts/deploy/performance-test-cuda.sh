#!/bin/bash

# AI-Karen CUDA Performance Test Script
# This script tests the performance of the CUDA deployment

set -e

echo "🏃 AI-Karen CUDA Performance Test"
echo "=================================="

# Check if services are running
if ! docker-compose -f docker-compose.cuda.yml ps | grep -q "Up"; then
    echo "❌ Services are not running. Please start with ./deploy-cuda.sh"
    exit 1
fi

# Test parameters
TEST_PROMPTS=(
    "Hello, how are you?"
    "What is the capital of France?"
    "Explain quantum computing in simple terms."
    "Write a short poem about artificial intelligence."
    "What are the main benefits of using GPU acceleration?"
)

# Warm-up test
echo "🔥 Warm-up test..."
if curl -s http://localhost:8000/health &> /dev/null; then
    echo "✅ AI-Karen application is responsive"
else
    echo "❌ AI-Karen application is not responding"
    exit 1
fi

# Performance test
echo "📊 Running performance tests..."
echo "=================================="

total_time=0
response_times=()

for i in "${!TEST_PROMPTS[@]}"; do
    prompt="${TEST_PROMPTS[$i]}"
    echo "Test $((i+1)): $prompt"
    
    # Measure response time
    start_time=$(date +%s.%N)
    
    # Send request to AI-Karen
    response=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"Phi-3-mini-4k-instruct\",
            \"messages\": [
                {\"role\": \"user\", \"content\": \"$prompt\"}
            ],
            \"max_tokens\": 100,
            \"temperature\": 0.7
        }" 2>/dev/null)
    
    end_time=$(date +%s.%N)
    
    # Calculate response time
    response_time=$(echo "$end_time - $start_time" | bc)
    response_times+=("$response_time")
    total_time=$(echo "$total_time + $response_time" | bc)
    
    echo "   Response time: ${response_time}s"
    
    # Check for errors
    if [[ $response == *"error"* ]]; then
        echo "   ⚠️  Error in response"
    else
        echo "   ✅ Response received"
    fi
    
    echo ""
done

# Calculate statistics
avg_time=$(echo "scale=2; $total_time / ${#TEST_PROMPTS[@]}" | bc)
max_time=$(printf '%s\n' "${response_times[@]}" | sort -n | tail -1)
min_time=$(printf '%s\n' "${response_times[@]}" | sort -n | head -1)

echo "📈 Performance Summary"
echo "===================="
echo "Total tests: ${#TEST_PROMPTS[@]}"
echo "Total time: ${total_time}s"
echo "Average response time: ${avg_time}s"
echo "Fastest response: ${min_time}s"
echo "Slowest response: ${max_time}s"

# GPU usage test
echo ""
echo "🖥️  GPU Usage During Test"
echo "========================"
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | while read -r gpu_util mem_used mem_total; do
    echo "GPU: ${gpu_util}% utilization, ${mem_used}MB used / ${mem_total}MB total"
done

# Memory usage test
echo ""
echo "💾 Memory Usage"
echo "=============="
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" ai-karen-vllm ai-karen-local-gguf ai-karen-api

# Test with larger prompt
echo ""
echo "🧩 Stress Test (larger prompt)"
echo "=============================="
large_prompt="Write a comprehensive explanation of the differences between CPU and GPU computing architectures, including their respective strengths, weaknesses, and ideal use cases. Include examples of modern applications that leverage both technologies effectively."

start_time=$(date +%s.%N)
response=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"Phi-3-mini-4k-instruct\",
        \"messages\": [
            {\"role\": \"user\", \"content\": \"$large_prompt\"}
        ],
        \"max_tokens\": 200,
        \"temperature\": 0.7
    }" 2>/dev/null)
end_time=$(date +%s.%N)

stress_test_time=$(echo "$end_time - $start_time" | bc)
echo "Large prompt response time: ${stress_test_time}s"
echo "Response length: ${#response} characters"

echo ""
echo "🎯 Performance test completed!"
ARG PROFILE=runtime

# -----------------------------
# Base build stage (common deps)
# -----------------------------
FROM python:3.11-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    cmake \
    pkg-config \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Runtime stage (default: CPU-only, BLAS off)
# -----------------------------
FROM base AS runtime
ENV CC=/usr/bin/gcc \
    CXX=/usr/bin/g++ \
    CMAKE_ARGS="-DLLAMA_METAL=off -DLLAMA_CUBLAS=off -DLLAMA_BLAS=off"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium && playwright install-deps chromium
RUN python -m spacy download en_core_web_sm || true
RUN mkdir -p /app/models/spacy && python -c "import spacy; nlp=spacy.load('en_core_web_sm'); nlp.to_disk('/app/models/spacy/en_core_web_sm')" || true

# -----------------------------
# Runtime-perf stage (OpenBLAS enabled)
# -----------------------------
FROM base AS runtime-perf
RUN apt-get update && apt-get install -y libopenblas-dev && rm -rf /var/lib/apt/lists/*
ENV CC=/usr/bin/gcc \
    CXX=/usr/bin/g++ \
    CMAKE_ARGS="-DLLAMA_METAL=off -DLLAMA_CUBLAS=off -DLLAMA_BLAS=on -DLLAMA_BLAS_VENDOR=OpenBLAS"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium && playwright install-deps chromium
RUN python -m spacy download en_core_web_sm || true
RUN mkdir -p /app/models/spacy && python -c "import spacy; nlp=spacy.load('en_core_web_sm'); nlp.to_disk('/app/models/spacy/en_core_web_sm')" || true

# -----------------------------
# Runtime-cuda stage (CUDA-enabled local GGUF build)
# Use API_BUILD_TARGET=runtime-cuda when building the API image on GPU hosts.
# -----------------------------
FROM nvidia/cuda:12.0.1-devel-ubuntu22.04 AS runtime-cuda
WORKDIR /app

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    curl \
    git \
    build-essential \
    cmake \
    pkg-config \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    python -m pip install --no-cache-dir --upgrade pip setuptools wheel

ENV CC=/usr/bin/gcc \
    CXX=/usr/bin/g++ \
    CMAKE_ARGS="-DGGML_CUDA=on -DLLAMA_CUBLAS=on -DLLAMA_METAL=off -DLLAMA_BLAS=off"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu120
RUN playwright install chromium && playwright install-deps chromium
RUN python -m spacy download en_core_web_sm || true
RUN mkdir -p /app/models/spacy && python -c "import spacy; nlp=spacy.load('en_core_web_sm'); nlp.to_disk('/app/models/spacy/en_core_web_sm')" || true

# -----------------------------
# Final stage (select by target)
# -----------------------------
FROM ${PROFILE} AS app
WORKDIR /app

ENV PYTHONPATH=/app:/app/src

COPY . .
RUN mkdir -p /app/models /app/logs /app/backups /app/certs /app/config
RUN mkdir -p /app/plugin_marketplace/ai/model-orchestrator

ENV PLUGIN_DIR="/app/plugin_marketplace" \
    MODELS_ROOT="/app/models" \
    CONFIG_PATH="/app/config"

EXPOSE 8000

# Liveness only: downstream dependency degradation must not trigger a restart loop.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# One public ASGI entrypoint for bare-process and container deployment.
CMD ["python", "-m", "uvicorn", "ai_karen_engine.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

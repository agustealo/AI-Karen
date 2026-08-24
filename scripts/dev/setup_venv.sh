#!/bin/bash
# Setup script for AI-Karen virtual environment

echo "🔧 Setting up AI-Karen virtual environment..."

# Detect available Python versions
echo "🔍 Detecting Python versions..."
PYTHON_VERSIONS=("python3.13" "python3.12" "python3.11" "python3")
SELECTED_PYTHON=""

# Check for available Python versions in order of preference
for py_cmd in "${PYTHON_VERSIONS[@]}"; do
    if command -v "$py_cmd" &> /dev/null; then
        PY_VERSION=$($py_cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        echo "Found $py_cmd version $PY_VERSION"
        
        # Check if version meets requirements (>=3.11)
        if [[ $(echo "$PY_VERSION >= 3.11" | bc -l) -eq 1 ]]; then
            SELECTED_PYTHON="$py_cmd"
            echo "✓ Selected $py_cmd (version $PY_VERSION) for virtual environment"
            break
        fi
    fi
done

if [ -z "$SELECTED_PYTHON" ]; then
    echo "❌ Error: No compatible Python version found (>=3.11 required)"
    exit 1
fi

# Remove existing broken virtual environment
if [ -d ".virEnv" ]; then
    echo "🗑️  Removing existing virtual environment..."
    rm -rf .virEnv
fi

# Create new virtual environment with selected Python version
echo "📦 Creating new virtual environment with $SELECTED_PYTHON..."
$SELECTED_PYTHON -m venv .virEnv

# Activate virtual environment and install dependencies
echo "📥 Activating virtual environment..."
source .virEnv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install poetry first
echo "📚 Installing poetry..."
pip install poetry

# Install project dependencies
echo "📦 Installing project dependencies..."
poetry install

# Install key dependencies directly with pip to ensure they're available
echo "🔧 Installing core dependencies..."
pip install fastapi uvicorn pydantic pydantic-settings python-dotenv

echo "✅ Virtual environment setup complete!"
echo ""
echo "To activate the environment, run:"
echo "  source .virEnv/bin/activate"
echo ""
echo "To run the project, use:"
echo "  ./run_karen.sh"
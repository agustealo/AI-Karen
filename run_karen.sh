#!/bin/bash
# AI-Karen Project Runner
# This script properly sets up the environment and runs the project

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "🚀 Starting AI-Karen Project..."
echo "📁 Project directory: $SCRIPT_DIR"

# Set environment file path
export ENV_FILE="$SCRIPT_DIR/.env"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
echo "📄 Environment file: $ENV_FILE"

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: .env file not found at $ENV_FILE"
    echo "Please ensure the .env file exists in the project root directory."
    exit 1
fi

# Change to project directory
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ -d ".virEnv" ]; then
    echo "🐍 Virtual environment found: .virEnv"

    # Check if virtual environment has proper Python
    if [ -f ".virEnv/bin/python3" ]; then
        echo "✓ Using virtual environment Python"

        # Check if core dependencies are available in virtual environment
        if .virEnv/bin/python3 -c "import fastapi; import crawl4ai" 2>/dev/null; then
            echo "✓ Dependencies available in virtual environment"

            # Ensure playwright browsers are installed in this environment
            # .virEnv/bin/python3 -m playwright install chromium

            # Run with canonical CLI entrypoint (defaults to start)
            CMD="${1:-start}"
            if [ $# -gt 0 ]; then shift; fi
            exec .virEnv/bin/python3 -m ai_karen_engine.cli "$CMD" "$@"
        else
            echo "❌ Error: Required dependencies (including crawl4ai) not found in .virEnv"
            echo "💡 Please ensure you have installed them: .virEnv/bin/pip install -r requirements.txt"
            exit 1
        fi
    else
        echo "❌ Error: .virEnv/bin/python3 not found."
        echo "💡 Please recreate the virtual environment or run ./setup_venv.sh"
        exit 1
    fi
else
    echo "❌ Error: Mandatory virtual environment '.virEnv' not found."
    echo "💡 The project now requires '.virEnv' to ensure consistent dependency management."
    echo "💡 Please run: python3 -m venv .virEnv && source .virEnv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
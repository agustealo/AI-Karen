#!/usr/bin/env python3
"""
AI-Karen API Server Launcher
This script starts the FastAPI application using uvicorn.
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

def main():
    """Start the FastAPI application."""
    print("🚀 Starting AI-Karen API Server...")
    
    # Import the app factory
    from ai_karen_engine.app import create_app
    
    # Create the FastAPI app
    app = create_app()
    
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("ENVIRONMENT", "production").lower() != "production"
    
    print(f"🌐 Server will be available at http://{host}:{port}")
    print(f"🔧 Environment: {os.getenv('ENVIRONMENT', 'production')}")
    print(f"🔄 Reload: {reload}")
    
    # Import and run uvicorn
    import uvicorn
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )

if __name__ == "__main__":
    main()
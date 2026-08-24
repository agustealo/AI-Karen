import os
import sys

# Add paths to sys.path
sys.path.insert(0, '/app/src')

try:
    from ai_karen_engine.clients.database.milvus_client import MilvusClient
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("Attempting to connect to Milvus...")
    # Explicitly use the environment variables if they exist, else use defaults
    host = os.getenv("MILVUS_HOST", "milvus")
    port = os.getenv("MILVUS_PORT", "19531")
    print(f"Connecting to {host}:{port}")
    
    client = MilvusClient(host=host, port=port)
    client._ensure_connected()
    print("Successfully connected to Milvus!")
    
    from pymilvus import utility
    with client._using() as alias:
        print(f"Collections: {utility.list_collections(using=alias)}")
        
except Exception as e:
    print(f"Failed to connect to Milvus: {e}")
    import traceback
    traceback.print_exc()

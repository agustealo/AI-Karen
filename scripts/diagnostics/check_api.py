
import asyncio
import sys
import os

# Mock paths
sys.path.append("/app/src")

from ai_karen_engine.api_routes.extensions.extensions import list_extensions_root, list_extensions

async def check():
    print("Checking extensions API...")
    try:
        print("\nTesting list_extensions_root()...")
        res_root = await list_extensions_root()
        print(f"Root Result length: {len(res_root)}")
        
        print("\nTesting list_extensions()...")
        res_list = await list_extensions()
        print(f"List Result length: {len(res_list)}")
        
    except Exception as e:
        print(f"❌ API Method failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check())

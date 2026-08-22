import asyncio
import sys
import os
from importlib.util import spec_from_file_location, module_from_spec

# Add src to sys.path
src_path = os.path.join(os.getcwd(), 'src')
sys.path.append(src_path)

def load_search_client():
    module_path = os.path.join(src_path, 'ai_karen_engine', 'extensions', 'plugins', 'intelligent-search', 'search_client.py')
    spec = spec_from_file_location("search_client", module_path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WebSearchClient

async def test_search():
    WebSearchClient = load_search_client()
    
    async with WebSearchClient() as client:
        # Try DuckDuckGo
        print("Testing DuckDuckGo...")
        response = await client.search("test query", max_results=5)
        print(f"Results: {len(response.results)}")
        if response.error:
            print(f"Error: {response.error}")
        for res in response.results:
            print(f"- {res.title} ({res.url})")

        # Try Brave Search Free
        print("\nTesting Brave Search Free...")
        try:
            # We call the internal method but it should now have a session
            response = await client._search_brave_free("test query", max_results=5)
            print(f"Results: {len(response.results)}")
            if response.error:
                print(f"Error: {response.error}")
            for res in response.results:
                print(f"- {res.title} ({res.url})")
        except Exception as e:
            print(f"Brave Search Free Error: {e}")

        # Try Mojeek
        print("\nTesting Mojeek...")
        try:
            response = await client._search_mojeek("test query", max_results=5)
            print(f"Results: {len(response.results)}")
            if response.error:
                print(f"Error: {response.error}")
            for res in response.results:
                print(f"- {res.title} ({res.url})")
        except Exception as e:
            print(f"Mojeek Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_search())

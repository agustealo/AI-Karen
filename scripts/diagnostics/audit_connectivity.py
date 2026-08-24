import sys
import os
import json
import requests

# Add paths to sys.path just in case
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

try:
    from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider
    print("Successfully imported OllamaProvider")
except ImportError as e:
    print(f"Failed to import OllamaProvider: {e}")

try:
    from ai_karen_engine.integrations.providers.gemini_provider import GeminiProvider
    print("Successfully imported GeminiProvider")
except ImportError as e:
    print(f"Failed to import GeminiProvider: {e}")

def audit_ollama():
    print("\n--- Auditing Ollama Connectivity ---")
    model = 'qwen3:4b'
    base_url = 'http://172.17.0.1:11434'
    print(f"Testing Ollama with model='{model}' and base_url='{base_url}'")
    
    # Direct requests call to see raw JSON for /generate
    try:
        prompt = "What is the square root of 123456789? Think step by step."
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        print(f"Sending request to {base_url}/api/generate with prompt: '{prompt}'...")
        resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=120)
        print(f"Status Code: {resp.status_code}")
        print("Raw JSON response from Ollama (/api/generate):")
        try:
            raw_json = resp.json()
            print(json.dumps(raw_json, indent=2))
        except Exception as je:
            print(f"Failed to parse JSON: {je}")
            print(resp.text)
            
        # Test /api/chat
        payload_chat = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        print(f"\nSending request to {base_url}/api/chat with prompt: '{prompt}'...")
        resp_chat = requests.post(f"{base_url}/api/chat", json=payload_chat, timeout=120)
        print(f"Status Code: {resp_chat.status_code}")
        print("Raw JSON response from Ollama (/api/chat):")
        try:
            raw_json_chat = resp_chat.json()
            print(json.dumps(raw_json_chat, indent=2))
        except Exception as je:
            print(f"Failed to parse JSON: {je}")
            print(resp_chat.text)

        # Now test with OllamaProvider
        print("\nTesting with OllamaProvider instance (generate_text with string prompt):")
        provider = OllamaProvider(model=model, base_url=base_url, timeout=120)
        try:
            response = provider.generate_text(prompt)
            print(f"OllamaProvider.generate_text(str) response: '{response}'")
        except Exception as e:
            print(f"OllamaProvider.generate_text(str) failed: {e}")

        print("\nTesting with OllamaProvider instance (generate_text with messages prompt):")
        try:
            response = provider.generate_text([{"role": "user", "content": "Say hello"}])
            print(f"OllamaProvider.generate_text(list) response: '{response}'")
        except Exception as e:
            print(f"OllamaProvider.generate_text(list) failed: {e}")
            
    except Exception as e:
        print(f"Direct request to Ollama failed: {e}")

def audit_gemini():
    print("\n--- Auditing Gemini Connectivity ---")
    # Check for keys in environment
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("No Gemini API key found in environment (GEMINI_API_KEY or GOOGLE_API_KEY).")
        return
    
    print(f"Found Gemini API key (starts with {api_key[:4]}...)")
    try:
        from ai_karen_engine.integrations.providers.gemini_provider import GeminiProvider
        provider = GeminiProvider(model="gemini-1.5-flash", api_key=api_key)
        response = provider.generate_text("Say hello")
        print(f"GeminiProvider.generate_text response: '{response}'")
    except Exception as e:
        print(f"GeminiProvider.generate_text failed: {e}")

if __name__ == "__main__":
    audit_ollama()
    audit_gemini()

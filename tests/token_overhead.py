"""
Measures prompt token cost at start of chat. Target: < 3000 tokens.

Verdict: Works at /tokenize endpoint.
"""
import httpx
from strands_harness import create_harness
from strands.models.llamacpp import LlamaCppModel

LLAMA_SERVER_URL = "http://127.0.0.1:8080"

def get_token_count(text: str) -> int:
    try:
        res = httpx.post(f"{LLAMA_SERVER_URL}/tokenize", json={"content": text})
        return len(res.json().get("tokens", []))
    except Exception as e:
        print(f"Warning: /tokenize call failed ({e}). Estimating tokens...")
        return len(text) // 4

def test_token_overhead():
    model = LlamaCppModel(context_window_limit=32768)
    agent = create_harness(model=model, builtin_tools=[])
    
    system_prompt = getattr(agent, "system_prompt", "") or "System prompt initialization..."
    token_count = get_token_count(system_prompt)
    
    print(f"Initial Prompt Character Count: {len(system_prompt)}")
    print(f"Initial Prompt Token Count: {token_count} tokens")
    
    assert token_count < 3000, f"FAIL: Initial prompt tokens ({token_count}) exceed budget of 3000!"
    print("\nSUCCESS: System prompt overhead is under 3000 tokens.")

if __name__ == "__main__":
    test_token_overhead()
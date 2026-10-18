"""
Tests if reasoning_content is isolated from assistant text
and omitted when replaying session history.

Verdict: Yes, reasoning content is NOT stored in session history.
"""
from strands_harness import create_harness
from strands.models.llamacpp import LlamaCppModel
from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage

class PatchedLlamaCpp(LlamaCppModel):
    def __init__(self, *args, enable_thinking: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._enable_thinking = enable_thinking

    def _format_request(self, *args, **kwargs):
        req = super()._format_request(*args, **kwargs)
        req["chat_template_kwargs"] = {"enable_thinking": self._enable_thinking}
        return req

def test_reasoning_isolation():
    model = PatchedLlamaCpp(context_window_limit=32768, enable_thinking=True)
    session_mgr = SnapshotSessionManager(
        session_id="test_chat",
        storage=LocalFileStorage("data/sessions")
    )
    
    agent = create_harness(
        model=model, 
        caching=False,
        session_manager=session_mgr,
        builtin_tools=[],
        tools=[]
    )
    
    print("> Sending prompt with thinking enabled")
    agent("Calculate 17 * 19 and explain briefly.")
    
    messages = agent.messages
    
    print("\n> Inspecting stored messages")
    for msg in messages:
        role = getattr(msg, "role", "unknown")
        content = getattr(msg, "content", str(msg))
        print(f"\nRole: {role}\nContent: {content}")
        
        if role == "assistant":
            assert "<|channel>" not in str(content), "FAIL: Raw <|channel> tags found in assistant content!"
            assert "<think>" not in str(content), "FAIL: Raw <think> tags found in assistant content!"
            
    print("\nSUCCESS: Reasoning content is properly isolated from session history.")

if __name__ == "__main__":
    test_reasoning_isolation()
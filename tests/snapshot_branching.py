"""
Tests snapshot saving, restoring, and branch isolation.

Verdict: If persistent (long term memory) is enabled, it WILL
store across branches so information from branch A WILL leak
into branch B. 
"""
import asyncio
import os
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

async def test_snapshot_branching():
    storage_path = "data/sessions"
    os.makedirs(storage_path, exist_ok=True)
    
    model = PatchedLlamaCpp(context_window_limit=32768, enable_thinking=False)
    session_mgr = SnapshotSessionManager(
        session_id="branch_test", 
        storage=LocalFileStorage(storage_path)
    )
    
    # Turn 1
    agent = create_harness(model=model, caching=False, session_manager=session_mgr, builtin_tools=[])
    print("--- Turn 1 ---")
    agent("Remember my favorite color is Blue.")
    
    # is_latest=False creates an immutable checkpoint and returns its snapshot_id string
    snap_1_id = await session_mgr.save_snapshot(agent, is_latest=False)
    print(f"Saved Immutable Snapshot 1 ID: {snap_1_id}")

    # Branch A: Turn 2a
    print("\n--- Branch A: Turn 2a ---")
    agent("I live in Mumbai.")
    
    # Restore Snapshot 1 onto agent for Branch B
    print(f"\nRestoring Snapshot 1 ({snap_1_id}) for Branch B...")
    restored = await session_mgr.restore_snapshot(agent, snapshot_id=snap_1_id)
    print(f"Restore Success: {restored}")
    
    # Branch B: Turn 2b
    print("\n--- Branch B: Turn 2b ---")
    response_b = agent("What city do I live in? Do you know?")
    print(f"Agent (Branch B): {response_b}")

    # Verify Branch B history does not contain "Mumbai" from Branch A
    messages_text = str([getattr(m, "content", str(m)) for m in agent.messages])
    
    if "Mumbai" in messages_text:
        print("FAIL: Leak detected from Branch A into Branch B!")
    else:
        print("\nSUCCESS (T3.1/T3.2): Snapshot restore isolated branches correctly.")

if __name__ == "__main__":
    asyncio.run(test_snapshot_branching())
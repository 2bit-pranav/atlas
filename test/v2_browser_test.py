import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from autogen_agentchat.ui import Console

from agent.browser_agent_v2.agent import create_browser_use_team
from agent.config import get_local_model


async def main() -> None:
    model_client = get_local_model()
    team = create_browser_use_team(model_client=model_client)

    try:
        while True:
            prompt = input("=" * 80 + "\nYou: ").strip()
            if prompt.lower() in {"exit", "quit", "bye"}:
                print("Exiting...")
                break

            if not prompt:
                continue

            print("\n[Browser-use team executing]\n")
            await Console(team.run_stream(task=prompt))
    finally:
        close = getattr(team, "close", None)
        if close is not None:
            await close()
        print("Browser-use team closed.")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.ProactorEventLoop)

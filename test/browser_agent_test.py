import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from autogen_agentchat.ui import Console

from agent.browser_agent.agent import create_browser_team
from agent.config import get_local_model, get_cloud_model


async def main() -> None:
    model_client = get_cloud_model()
    team = create_browser_team(model_client=model_client)

    participants = getattr(team, "_participants", getattr(team, "participants", []))

    try:
        while True:
            prompt = input("=" * 80 + "\nYou: ").strip()
            if prompt.lower() in {"exit", "quit", "bye"}:
                print("Exiting...")
                break

            await Console(team.run_stream(task=prompt))
    finally:
        for participant in participants:
            close = getattr(participant, "close", None)
            if close is not None:
                await close()
        print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.ProactorEventLoop)

import asyncio
from typing import Optional
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from config import (
    get_model_client,
    USE_LOCAL_MODEL,
)
from tools import web_search, web_fetch

SYSTEM_MESSAGE = """
You are Atlas, a helpful AI assistant.

Guidelines:
- Whenever current information is required, always use web_search.
- web_search already returns rich evidence including extracted page text,
  summaries and highlights.
- Only use web_fetch when the user explicitly asks to inspect a particular URL
  or when you need additional detail from one source.
- Always synthesize information.
- Never dump raw tool output.
- Mention important sources naturally.
"""

class AtlasAgent:
    def __init__(self, use_local: Optional[bool] = None):
        if use_local is None:
            use_local = USE_LOCAL_MODEL

        self.agent = AssistantAgent(
            name="Atlas",
            model_client=get_model_client(use_local),
            tools=[
                web_search,
                web_fetch,
            ],
            system_message=SYSTEM_MESSAGE,
            reflect_on_tool_use=True,
        )

    async def chat(self, prompt: str):
        result = await self.agent.run(task=prompt)
        print(result.messages)
        agent_state = await self.agent.save_state()
        print(agent_state)


async def main():
    agent = AtlasAgent()
    print("Atlas Ready.\n")
    while True:
        prompt = input("You: ").strip()

        if prompt.lower() in {"exit", "quit", "bye"}:
            break

        await agent.chat(prompt)
        print()


if __name__ == "__main__":
    asyncio.run(main())

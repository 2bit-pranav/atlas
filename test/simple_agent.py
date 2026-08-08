import asyncio
import os
from dotenv import load_dotenv
from autogen_core.models import ModelInfo
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient

load_dotenv()

async def main() -> None:
    model_client = OpenAIChatCompletionClient(
        model="gemma-4-E2B_q4_0-it",
        # model="gemini-3.5-flash-lite",
        base_url="http://127.0.0.1:8000/",
        api_key="bypass",
        model_info=ModelInfo(
            vision=True,
            function_calling=True,
            structured_output=True,
            json_output=True,
            family="unknown",
        ),
    )

    def calculate_system_load(server_name: str) -> str:
        """Returns the current CPU load for a given server."""
        print(f"\n[🔧 TOOL EXECUTED] Checking load for {server_name}...")
        return f"The CPU load for {server_name} is at 84%."

    agent = AssistantAgent(
        name="Atlas",
        model_client=model_client,
        tools=[calculate_system_load],
        system_message="You are Atlas, a helpful and precise AI assistant running locally. Keep your answers concise.",
    )

    while True:
        user_prompt = input("\nYou: ")
        if user_prompt.strip().lower() in ["exit", "quit"]:
            print("Shutting down")
            break

        await Console(agent.run_stream(task=user_prompt))

if __name__ == "__main__":
    asyncio.run(main())

# llama serve -m "C:\Users\prana\Desktop\atlas\llm\gemma-4-E2B_q4_0-it.gguf" --mmproj "C:\Users\prana\Desktop\atlas\llm\gemma-4-E2B-it-mmproj.gguf" --port 8000 -c 64000 --jinja --reasoning auto
import asyncio
import os
import sys
from dotenv import load_dotenv
from autogen_core.models import ModelInfo
from autogen_agentchat.teams import MagenticOneGroupChat, SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.agents.file_surfer import FileSurfer
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.models.openai import OpenAIChatCompletionClient

load_dotenv()

async def write_file(file_path: str, content: str) -> str:
    """Creates or overwrites a text file at file_path with the specified content.
    Automatically creates directories if they do not exist.
    """
    try:
        abs_path = os.path.abspath(file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File successfully written to: {abs_path}"
    except Exception as e:
        return f"Failed to write file: {str(e)}"


async def update_file(file_path: str, content: str) -> str:
    """Appends new text content to an existing file at file_path."""
    try:
        abs_path = os.path.abspath(file_path)
        with open(abs_path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"File successfully updated at: {abs_path}"
    except Exception as e:
        return f"Failed to update file: {str(e)}"

async def run_without_code_executor():
    client = OpenAIChatCompletionClient(
        model="gemini-3.1-flash-lite",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=os.getenv("CLOUD_API_KEY"),
        model_info=ModelInfo(
            vision=True,
            function_calling=True,
            structured_output=True,
            json_output=True,
            family="unknown",
        ),
    )

    web_surfer = MultimodalWebSurfer(
        "WebSurfer", 
        model_client=client,
        description="Searches the web to retrieve requested data.",
    )
    file_surfer = FileSurfer(
        "FileSurfer", 
        model_client=client,
        description="Reads existing file contents. THIS IS A READ-ONLY agent.",
    )
    file_writer = AssistantAgent(
        name="FileWriterAgent",
        model_client=client,
        description="Writes content to disk using write_file after WebSurfer gets data, and updates file contents using update_file.",
        tools=[write_file, update_file],
        system_message=(
            "You are a file system assistant. Use your tools (`write_file` or `update_file`) "
            "directly whenever you need to create, write, or update files on disk."
        ),
    )
    evaluator = AssistantAgent(
        name="Evaluator",
        model_client=client,
        description="Evaluates overall completion. Selected ONLY after FileWriter has run.",
        system_message=(
            "You are a completion validator.\n"
            "CRITICAL RULES:\n"
            "1. Check the message history for a successful `write_file` tool output (containing 'SUCCESS: File saved').\n"
            "2. If `write_file` returned a SUCCESS message containing the requested data format, the task is 100% COMPLETE. "
            "Output 'FINAL_TASK_COMPLETE' immediately.\n"
            "3. Do NOT inspect WebSurfer's browser state or ask WebSurfer to scroll/navigate after `write_file` has succeeded.\n"
            "4. Only reject completion if `write_file` threw an ERROR or was never called."
        )
    )

    termination = TextMentionTermination("FINAL_TASK_COMPLETE") | MaxMessageTermination(max_messages=10)

    team = SelectorGroupChat(
        participants=[web_surfer, file_surfer, file_writer, evaluator],
        model_client=client,
        termination_condition=termination,
    )

    current_dir = os.getcwd().replace("\\", "/")
    task = (
        f"Find out the last 10 Formula 1 World Champions and their constructors. "
        f"Save the results into '{current_dir}/f1_champions.txt' in format 'Year: Driver - Constructor'."
    )   
    await Console(team.run_stream(task=task))

    await web_surfer.close()
    await file_surfer.close()
    await client.close()

if __name__ == "__main__":
    asyncio.run(run_without_code_executor())

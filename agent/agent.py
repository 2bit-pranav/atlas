import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.ui import Console
from autogen_ext.agents.file_surfer import FileSurfer

from config import get_local_model, get_cloud_model
from tools import web_search, web_fetch, write_file

load_dotenv()

current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")


class AtlasAgent:
    def __init__(self):
        # Cloud model handles selector routing and reasoning reliably
        cloud_model = get_cloud_model()
        # Local model can be used for sub-agents if desired, or cloud for maximum speed
        local_model = get_local_model()

        # 1. Research Agent (Fast Exa Web Search)
        self.researcher = AssistantAgent(
            name="ResearchAgent",
            model_client=cloud_model,
            description="Searches the web for facts, rankings, sports results, and real-time data using Exa search.",
            system_message=f"""
            You are a Web Research Specialist. Current datetime: {current_datetime}.
            
            DUTIES:
            - Use `web_search` or `web_fetch` to gather accurate data requested by the user.
            - Once search results are received, present the clear, structured output in the chat.
            - Do NOT attempt to write or save files yourself.
            """,
            tools=[web_search, web_fetch],
            reflect_on_tool_use=False,
        )

        # 2. File Writer Agent (Single Responsibility: Write to Disk)
        self.file_writer = AssistantAgent(
            name="FileWriterAgent",
            model_client=cloud_model,
            description="Selected ONLY AFTER data is available in chat and needs to be written or updated on disk.",
            system_message="""
            You are a File System Specialist.
            
            DUTIES:
            - Inspect the chat history for the data collected by ResearchAgent or user instructions.
            - Immediately invoke `write_file` or `update_file` to save the exact formatted data to the specified path.
            - Always confirm completion after the tool execution finishes.
            """,
            tools=[write_file],
            reflect_on_tool_use=False,
        )

        # 3. File Reader Agent (Read-only inspection)
        self.file_reader = FileSurfer(
            name="FileReaderAgent",
            model_client=local_model,
            description="Reads and inspects local files on disk when the user asks to analyze existing file content.",
        )

        # 4. Evaluator Agent (Pipeline Termination Guard)
        self.evaluator = AssistantAgent(
            name="Evaluator",
            model_client=cloud_model,
            description="Selected ONLY AFTER FileWriterAgent or ResearchAgent has completed the full user request.",
            system_message="""
            You are a Task Completion Validator.
            
            RULES:
            1. If the user asked to save/write a file, check if `FileWriterAgent` successfully called `write_file`.
            2. If `write_file` returned a success message OR if a simple query was completely answered, output:
               FINAL_TASK_COMPLETE
            3. Output ONLY 'FINAL_TASK_COMPLETE' when the entire user request is 100% satisfied.
            """,
        )

    def _build_team(self) -> SelectorGroupChat:
        cloud_model = get_cloud_model()

        # Stops execution immediately when Evaluator outputs FINAL_TASK_COMPLETE
        termination = (
            TextMentionTermination("FINAL_TASK_COMPLETE")
            | MaxMessageTermination(max_messages=8)
        )

        return SelectorGroupChat(
            participants=[
                self.researcher,
                self.file_writer,
                self.file_reader,
                self.evaluator,
            ],
            model_client=cloud_model,  # Cloud Selector guarantees accurate agent transitions
            termination_condition=termination,
        )

    async def chat(self, prompt: str):
        team = self._build_team()
        await Console(team.run_stream(task=prompt))


async def main():
    atlas = AtlasAgent()
    print("Atlas Team System Ready.\n")

    while True:
        prompt = input("=" * 80 + "\nYou: ").strip()
        if prompt.lower() in {"exit", "quit", "bye"}:
            break
        await atlas.chat(prompt)


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=asyncio.ProactorEventLoop,
    )
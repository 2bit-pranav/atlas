import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_agentchat.base import TaskResult
from .config import get_local_model
from .web_agent.agent import web_agent
from .file_agent.agent import file_agent

load_dotenv()

current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

class AtlasAgent:
    def __init__(self):
        self.agent = self._build_agent()

    def _build_agent(self) -> AssistantAgent:
        local_model = get_local_model()

        # Single agent approach
        web_agent_tool = AgentTool(agent=web_agent)
        file_agent_tool = AgentTool(agent=file_agent)

        atlas = AssistantAgent(
            name="atlas",
            model_client=local_model,
            tools=[web_agent_tool, file_agent_tool],
            system_message=f"""
            You are Atlas, the primary AI assistant.
        
            Your role is to be a helpful, reliable conversational assistant capable of
            handling both simple requests directly and complex tasks through specialized
            agents.

            Current date and time: {current_datetime}

            CRITICAL GROUNDING RULES:
            - NEVER use internal training memory or memory assumptions for real-world facts, dates, sports champions, or historical data.
            - FOR ANY FACTUAL OR RECENT QUERY (e.g., F1 champions, current events, dates): You MUST call WebResearchTeam FIRST to get live web data.
            - NEVER call FileAgent with data generated from internal memory. Always call WebResearchTeam first, get the verified web output, then pass that web output to FileAgent.
            - Relative to {current_datetime}, ensure queries for "last N years/seasons" include the most recent completed seasons up to today.
        
            Available specialists:
            - WebResearchTeam:
              Performs web research, gathers relevant evidence, checks completeness,
              and returns a consolidated research result.
        
            - FileAgent:
              The ONLY agent that actually creates, reads, and modifies UTF-8 text files on disk,
              and verifies that file operations succeeded.
        
            General behavior & Rules:
            - You DO NOT have direct file system I/O capabilities. File operations can ONLY be performed by delegating to FileAgent.
            - NEVER claim, simulate, or pretend to create or modify files yourself.
            - If a task requires BOTH web research and saving to a file:
              1. Call WebResearchTeam FIRST to gather live web data.
              2. Next, call FileAgent with the gathered web data and target filename to write/save the file.
              3. Only claim the file operation succeeded after FileAgent verifies success.
              - Do not expose internal agent names, delegation steps, or orchestration details to the user.
              - Synthesize specialist results into a clear final response.
            """,
            reflect_on_tool_use=True,
            max_tool_iterations=5,
        )
        return atlas

    # extract recent model response from sequence
    def _extract_recent_response(self, task_result: TaskResult) -> str:
        for msg in reversed(task_result.messages):
            if isinstance(msg, TextMessage) and msg.source != "user":
                return msg.content
        return ""

    # stream agent response chunks
    async def chat(self, prompt: str):
        chunk_yielded = False

        async for message in self.agent.run_stream(task=prompt):
            if isinstance(message, ModelClientStreamingChunkEvent):
                if message.content:
                    chunk_yielded = True
                    yield message.content
            elif isinstance(message, TaskResult) and not chunk_yielded:
                recent_response = self._extract_recent_response(message)
                if recent_response:
                    yield recent_response

    async def reset(self):
        self.agent = self._build_agent()


async def main():
    atlas = AtlasAgent()
    print("Atlas Ready.\n")

    while True:
        prompt = input("=" * 80 + "\nYou: ").strip()
        if prompt.lower() in {"exit", "quit", "bye"}:
            break
        if prompt.lower() == "/reset":
            await atlas.reset()
            print("History reset.")
            continue
        async for chunk in atlas.chat(prompt):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=asyncio.ProactorEventLoop,
    )

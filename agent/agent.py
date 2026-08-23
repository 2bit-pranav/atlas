import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.ui import Console
from .config import get_local_model, get_cloud_model
from .web_agent.agent import web_agent
from .file_agent.agent import file_agent

load_dotenv()

current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

class AtlasAgent:
    def _build_team(self) -> SelectorGroupChat:
        cloud_model = get_cloud_model()
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

        # --- Alternative Outer Team Approach (Solution 2) ---
        # chat_agent = AssistantAgent(
        #     name="chat_agent",
        #     model_client=local_model,
        #     description="Primary orchestrator for user queries. Does NOT have direct tools; must orchestrate web_agent then file_agent.",
        #     system_message=f"""
        #     You are Atlas, the main conversational coordinator.
        #     Current time: {current_datetime}.
        #
        #     CRITICAL DELEGATION & GROUNDING RULES:
        #     - You are an orchestrator ONLY. You DO NOT have direct file tools and DO NOT have web tools.
        #     - NEVER guess, hallucinate, or recall factual statistics (like F1 champions) from internal memory.
        #     - STEP 1: Select web_agent FIRST to perform live web research.
        #     - STEP 2: Wait for web_agent to complete research and output DATA_COMPLETE.
        #     - STEP 3: Select file_agent to write the verified web research output to disk.
        #     - STEP 4: Only after file_agent completes with FILE_TASK_COMPLETE, provide the final response to the user and include 'FINAL_TASK_COMPLETE' on its own line.
        #     """,
        # )
        #
        # termination = TextMentionTermination("FINAL_TASK_COMPLETE") | MaxMessageTermination(max_messages=10)
        #
        # team = SelectorGroupChat(
        #     name="atlas_team",
        #     participants=[
        #         chat_agent,
        #         web_agent,
        #         file_agent,
        #     ],
        #     model_client=local_model,
        #     termination_condition=termination,
        # )
        # return team

    async def chat(self, prompt: str):
        atlas = self._build_team()
        await Console(atlas.run_stream(task=prompt))


async def main():
    atlas = AtlasAgent()
    print("Atlas Ready.\n")

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

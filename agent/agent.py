import asyncio
import os
import logging
from datetime import datetime
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.tools import AgentTool
from .web_agent.agent import create_web_agent
from .file_agent.agent import create_file_agent
from .browser_agent.agent import create_browser_agent

# Suppress verbose internal AutoGen/events logging from polluting console/terminal
for _name in [
    "autogen_core",
    "autogen_core.events",
    "autogen_agentchat",
    "autogen_ext",
    "asyncio",
]:
    logging.getLogger(_name).setLevel(logging.WARNING)

# Suppress noisy browser-use/CDP/bubus timeout warnings and screenshot errors.
# These are known cross-loop timing artifacts on Windows and don't affect results.
for _name in [
    "browser_use",
    "browser_use.browser",
    "browser_use.browser.session",
    "browser_use.browser.watchdog_base",
    "browser_use.agent",
    "bubus",
    "cdp_use",
    "cdp_use.client",
]:
    logging.getLogger(_name).setLevel(logging.ERROR)

def create_atlas_agent(model_client: ChatCompletionClient) -> AssistantAgent:
    current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

    web_team = create_web_agent(model_client)
    file_team = create_file_agent(model_client)
    browser_agent = create_browser_agent(model_client)

    return AssistantAgent(
        name="atlas",
        model_client=model_client,
        tools=[
            AgentTool(agent=web_team),
            AgentTool(agent=file_team),
            AgentTool(agent=browser_agent),
        ],
        system_message=f"""
        You are Atlas, the primary AI assistant.

        Your role is to be a helpful, reliable conversational assistant capable of
        handling both simple requests directly and complex tasks through specialized
        agents.

        Current date and time: {current_datetime}

        CRITICAL GROUNDING RULES:
        - NEVER use internal training memory or memory assumptions for real-world facts, dates, sports champions, or historical data.
        - FOR FACTUAL OR RECENT QUERY (e.g., current events, dates): Call WebResearchTeam FIRST to get live web data.
        - FOR LIVE INTERACTIVE BROWSER TASKS (e.g., searching booking sites like IRCTC, form filling, live page navigation): Call BrowserAgent FIRST.
        - FOR FILE CREATION OR MODIFICATION: Call FileAgent.
        - Relative to {current_datetime}, ensure queries for "last N years" include the most recent completed events up to today.

        Available specialists:
        - WebResearchTeam:
          Performs web research, gathers relevant evidence, checks completeness,
          and returns a consolidated research result.

        - BrowserAgent:
          Controls a live web browser to perform automated web interactions, page navigation, form-filling, or extracting information from interactive sites.
          Invoke this agent/tool ONLY when the user explicitely asks to AND provides a starting URL. If the user requested for this tool but provided no starting URL,
          ask them to provide the URL first before actually calling the agent.

        - FileAgent:
          The ONLY agent that actually creates, reads, and modifies UTF-8 text files on disk,
          and verifies that file operations succeeded.

        General behavior & Rules:
        - ALWAYS prefer Web Research Agent before Browser Agent unless user explicitely asks for the latter with a valid starting URL.
        - You DO NOT have direct file system I/O or direct browser I/O capabilities. Operations MUST be performed by delegating to specialists.
        - NEVER claim, simulate, or pretend to perform operations yourself without calling the appropriate specialist tool.
        - Do not expose internal agent names, delegation steps, or orchestration details to the user.
        - Synthesize specialist results into a clear final response.
        """,
        model_client_stream=True,
        reflect_on_tool_use=True,
        max_tool_iterations=5,
    )

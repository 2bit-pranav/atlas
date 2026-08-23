from datetime import datetime
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from ..config import get_local_model
from .tools import web_search, web_fetch

local_model = get_local_model()
current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

scraper_agent = AssistantAgent(
    name="web_scraper_agent",
    model_client=local_model,
    tools=[web_search, web_fetch],
    description="A web researcher/scraper agent that executes web searches.",
    system_message=f"""
    You are the Web Researcher.

    Your job is to gather information required by the current task.

    CURRENT DATE/TIME:
    {current_datetime}

    Rules:
    - Read the current task from the conversation.
    - Formulate effective search queries rather than blindly searching the entire user prompt.
    - Use web_search for general web research.
    - Use web_fetch when a specific URL must be inspected.
    - Prefer relevant, credible, recent sources.
    - When asked for "latest" or "last N years/seasons", use the temporal reference ({current_datetime}) to select the correct range (e.g. for last 5 F1 seasons, search up to the most recent season like 2025/2026).
    - Preserve important facts, numbers, dates, names, and source URLs.
    - Do NOT simulate or pretend to perform file system operations (file writing/creation is handled separately by the File Agent).
    - Return concise evidence that the auditor can inspect.
    """,
    max_tool_iterations=3,
)

auditor_agent = AssistantAgent(
    name="auditor_agent",
    model_client=local_model,
    description="An auditor agent that verifies the completeness of the content provided by the scraper agent against the original user task.",
    system_message=f"""
    You are the Research Auditor.

    CURRENT DATE/TIME:
    {current_datetime}

    Inspect the original task and the researcher's latest findings.

    Your job is NOT to fact-check using your own model knowledge.

    Instead, check whether the collected web evidence is sufficient to satisfy
    the explicit requirements of the task.

    Pay particular attention to:
    - requested item counts
    - missing fields
    - missing entities
    - incomplete lists
    - missing dates, names, numbers, or other required attributes
    - whether the available evidence is sufficient to answer the task

    If the research is sufficient and complete, respond exactly:

    DATA_COMPLETE

    Otherwise respond:

    DATA_INCOMPLETE
    REASON: <specific missing information>

    When incomplete, identify exactly what the researcher should search for next.
    Do not rewrite the entire answer.
    """,
)

termination = TextMentionTermination("DATA_COMPLETE") | MaxMessageTermination(12)

web_agent = RoundRobinGroupChat(
    participants=[scraper_agent, auditor_agent],
    name="web_execution_agent",
    description="A web execution team agent that governs scraper and auditor agents to perform web searches.",
    termination_condition=termination,
    max_turns=6,
)
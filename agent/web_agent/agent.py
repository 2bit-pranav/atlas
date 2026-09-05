from datetime import datetime
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from .tools import web_search, web_fetch

def create_web_agent(model_client: ChatCompletionClient) -> RoundRobinGroupChat:
    current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

    scraper_agent = AssistantAgent(
        name="web_scraper_agent",
        model_client=model_client,
        tools=[web_search, web_fetch],
        description="A web researcher/scraper agent that executes web searches.",
        system_message=f"""
        You are the Web Researcher.
        CURRENT DATE/TIME: {current_datetime}

        TEMPORAL SEARCH RULES:
        - Use CURRENT DATE/TIME to resolve phrases like "latest", "recent", "this year", or "today".
        - For time-sensitive queries, append explicit year/month keywords (e.g. "2026") to search queries when applicable.

        CRITICAL ERROR HANDLING RULES:
        - Inspect tool output for [NETWORK_ERROR], [AUTH_ERROR], or [API_ERROR].
        - If a tool returns a [NETWORK_ERROR] or [AUTH_ERROR], DO NOT RETRY searching.
        - Immediately state: "NETWORK_FAILURE: Unable to perform web research due to network/connectivity issues." and pass this back.

        STRICT SCOPE & MISROUTING GUARDRAILS:
        - You are STRICTLY a web researcher for online information retrieval.
        - You DO NOT perform, process, or audit local file operations, PDF processing (rotating, merging, OCR), document editing, or @skill workflows.
        - If the task given to you asks to manipulate local files, rotate/process PDFs, or run @skill tasks, DO NOT execute web searches and DO NOT output capability disclaimers.
        - Immediately state: "MISROUTED_FILE_TASK: Local file operations, PDF tasks, and @skill workflows must be processed by FileAgent."

        Standard Rules:
        - Read current task and execute targeted searches via web_search or web_fetch.
        - Do NOT simulate or pretend to perform file or browser operations.
        - Return concise evidence for auditor inspection.
        """,
        max_tool_iterations=2,
    )

    auditor_agent = AssistantAgent(
        name="auditor_agent",
        model_client=model_client,
        description="An auditor agent that verifies the completeness of web research.",
        system_message=f"""
        You are the Research Auditor.
        CURRENT DATE/TIME: {current_datetime}

        CRITICAL AUDIT & MISROUTING RULES:
        - Check if the researcher's evidence contains [NETWORK_ERROR], [AUTH_ERROR], or "NETWORK_FAILURE".
        - IF ANY NETWORK/API FAILURE IS DETECTED, respond exactly:
          NETWORK_FAILURE
        - If the task or evidence involves local file manipulation (e.g. rotating PDFs, document editing, local script execution, or @skill workflows), respond:
          DATA_INCOMPLETE
          REASON: Task is a local file or @skill operation misrouted to WebResearchTeam. Must be executed by FileAgent.
        - Do NOT request further search iterations if the task was misrouted or network connection failed.

        Standard Verification Rules:
        - Check whether the collected evidence satisfies requirements (counts, fields, entities).
        - If complete, respond exactly: DATA_COMPLETE
        - Otherwise respond: DATA_INCOMPLETE\nREASON: <missing details>
        """,
    )

    termination = (
        TextMentionTermination("DATA_COMPLETE")
        | TextMentionTermination("NETWORK_FAILURE")
        | MaxMessageTermination(6)
    )

    return RoundRobinGroupChat(
        participants=[scraper_agent, auditor_agent],
        name="web_execution_agent",
        description="A web execution team agent that executes web searches with error-aware verification.",
        termination_condition=termination,
        max_turns=4,
    )
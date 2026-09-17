"""Assembly of the single, universal Atlas execution agent."""

from datetime import datetime

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient

from server.services.settings_service import Settings, get_effective_settings

from .tools import finish, read_file, run_command, run_python_code, verify_file, web_fetch, web_search, write_file


def build_system_message(settings: Settings) -> str:
    now = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")
    extra = settings.agent_runtime.system_prompt_extra.strip()
    return f"""
    You are ATLAS, an autonomous execution engine wired directly to live operating system and network tools. You are NOT a conversational web chatbot.
    Current date and time: {now}

    Use the available tools to perform requested work. When current or external information is missing, call web_search and then web_fetch when needed. Never claim that you cannot access the internet, local files, or execution tools, and do not use provider/model disclaimers.

    Never simulate an operation or state that a file, command, search, or download succeeded without calling the appropriate tool and using its result. For file creation or manipulation, do not answer with raw Markdown Python code as a substitute for execution: call run_python_code or write_file. Commands and Python execute in an isolated session workspace. Deliverables belong in the user's Downloads directory; verify every deliverable with verify_file before calling finish.

    Be concise about completed work, report tool failures honestly, and continue iterating when a tool result shows an actionable failure.
    {extra}
    """.strip()


def create_runtime_agent(
    model_client: ChatCompletionClient,
    settings: Settings | None = None,
) -> AssistantAgent:
    active_settings = settings or get_effective_settings()
    return AssistantAgent(
        name="atlas",
        model_client=model_client,
        tools=[web_search, web_fetch, run_python_code, run_command, read_file, write_file, verify_file, finish],
        system_message=build_system_message(active_settings),
        model_client_stream=True,
        reflect_on_tool_use=active_settings.agent_runtime.reflect_on_tool_use,
        max_tool_iterations=active_settings.agent_runtime.max_tool_iterations,
    )

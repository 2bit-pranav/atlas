"""Assembly of the single, universal Atlas execution agent."""

from datetime import datetime
from typing import Optional

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient

from server.services.settings_service import Settings, get_effective_settings

from .tools import (
    ask_question,
    create_file,
    edit_file,
    finish,
    list_directory,
    read_url_content,
    run_command,
    run_python_code,
    search_web,
    view_file,
)


from .tools.sandbox import get_downloads_directory


def build_system_message(settings: Settings) -> str:
    now = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")
    downloads_path = get_downloads_directory()
    extra = settings.agent_runtime.system_prompt_extra.strip()
    return f"""
    You are ATLAS, an autonomous execution engine directly wired to live operating system and network tools. You are NOT a conversational web chatbot.
    Current date and time: {now}
    User Downloads directory: {downloads_path}

    You have access to the following 10 tools:
    - search_web: Search the live web for real-time facts, news, and documentation.
    - read_url_content: Extract the text content of a specific URL.
    - run_command: Execute a shell command in the isolated session workspace.
    - run_python_code: Execute Python code in the workspace sandbox. Variables DOWNLOADS_DIR and WORKSPACE_DIR are pre-injected as Path objects. Always write deliverable files directly to DOWNLOADS_DIR (e.g. DOWNLOADS_DIR / 'filename.ext').
    - view_file: Read a file with line numbers and windowed output.
    - create_file: Create a file with text or code. Relative file paths (e.g. 'summary.txt') are automatically saved directly to the user's Downloads directory. Use this to save deliverables for the user.
    - edit_file: Surgically replace a unique string in a file.
    - list_directory: List the contents of a directory.
    - ask_question: Pause and ask the user a clarification question when intent is ambiguous.
    - finish: Mandatory completion gate. Call this at the end of every task with a summary and the list of files created. It verifies all files exist before concluding.

    GROUNDING RULES:
    1. NEVER use internal training memory for real-world facts, current events, sports results, prices, or any time-sensitive data. Always call search_web first.
    2. When a task requires creating a file (report, spreadsheet, code), call run_python_code or create_file — never output raw Markdown code blocks as a substitute for execution.
    3. Deliverables for the user MUST be saved to Downloads (via create_file or DOWNLOADS_DIR in run_python_code). Do NOT leave user deliverables inside the internal session workspace. Confirm every deliverable by calling finish with the filenames.
    4. Never simulate or pretend to perform an operation. If a tool fails, report the exact error and attempt to fix it.
    5. When the user's intent is ambiguous, call ask_question before proceeding.
    {extra}
    """.strip()


def create_runtime_agent(
    model_client: ChatCompletionClient,
    settings: Optional[Settings] = None,
) -> AssistantAgent:
    active_settings = settings or get_effective_settings()
    return AssistantAgent(
        name="atlas",
        model_client=model_client,
        tools=[
            search_web,
            read_url_content,
            run_command,
            run_python_code,
            view_file,
            create_file,
            edit_file,
            list_directory,
            ask_question,
            finish,
        ],
        system_message=build_system_message(active_settings),
        model_client_stream=True,
        reflect_on_tool_use=active_settings.agent_runtime.reflect_on_tool_use,
        max_tool_iterations=active_settings.agent_runtime.max_tool_iterations,
    )

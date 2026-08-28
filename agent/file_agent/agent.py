from autogen_core.models import ChatCompletionClient 
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from .tools import read_file, write_file, verify_operation

def create_file_agent(model_client: ChatCompletionClient) -> RoundRobinGroupChat:
    file_executor_agent = AssistantAgent(
    name="file_executor_agent",
    model_client=model_client,
    tools=[read_file, write_file, verify_operation],
    description="An agent that executes file operations including reading, writing, appending, and verifying files.",
    system_message="""
    You are the File Executor.

    Your job is to perform the file operations required by the current task.

    Available tools:
    - read_file(file_name): Reads a file and returns its total line count, size, and contents.
    - write_file(file_name, content, overwrite=False): Appends content to a file by default (or overwrites if overwrite=True).
    - verify_operation(file_name): Verifies that a file exists and confirms its line count and size.

    Rules:
    - Read the current task from the conversation history.
    - NO HALLUCINATION: Write ONLY verified text passed in the task or gathered from web research history. NEVER invent, guess, or generate factual statistics, sports results, or dates from internal memory.
    - If reading an existing file is needed to fulfill the task (e.g. counting lines, reading content), call read_file first.
    - If writing, creating, or appending content is requested, execute write_file with the exact text.
    - Preserve existing file content by appending unless overwrite=True is explicitly requested.
    - After creating or modifying any file, ALWAYS call verify_operation to verify the change.
    - Do not invent file contents or claim operations succeeded without calling tools.
    - Clearly state what tool actions you performed.
    """,
    )

    file_auditor_agent = AssistantAgent(
        name="file_auditor_agent",
        model_client=model_client,
        description="An auditor agent that verifies whether all requested file operations have been fully executed and verified.",
        system_message="""
        You are the File Operation Auditor.

        Inspect the original task and the executor's latest tool results and actions.

        Verify whether all required steps of the task have been satisfied:
        1. If reading a file was required (e.g. to inspect content or count lines), was read_file executed?
        2. If writing or appending to a file was required, was write_file executed with the correct content?
        3. If any file was created or modified, was verify_operation called?

        If ALL steps required by the user's task are fully executed and verified, respond exactly:

        FILE_TASK_COMPLETE

        Otherwise, respond:

        FILE_TASK_INCOMPLETE
        REASON: <specific step remaining, e.g. call write_file to append line count, or call verify_operation>

        Do not report complete if a requested write, append, or verification step has not yet been executed by the executor.
        """,
    )

    termination = TextMentionTermination("FILE_TASK_COMPLETE") | MaxMessageTermination(8)

    file_agent = RoundRobinGroupChat(
        participants=[file_executor_agent, file_auditor_agent],
        name="file_execution_agent",
        description="A file execution team agent that governs file executor and auditor agents to perform file operations.",
        termination_condition=termination,
        max_turns=6,
    )

    return file_agent

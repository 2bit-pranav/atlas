from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ChatCompletionClient
from .tools import (
    create_docx_document,
    create_excel_spreadsheet,
    create_pdf_document,
    save_text_file,
    verify_file,
)

def create_file_agent(model_client: ChatCompletionClient) -> RoundRobinGroupChat:
    """Factory creating the File Execution Team agent."""

    file_executor_agent = AssistantAgent(
        name="file_executor_agent",
        model_client=model_client,
        tools=[
            save_text_file,
            create_pdf_document,
            create_docx_document,
            create_excel_spreadsheet,
            verify_file,
        ],
        description="Executes file generation and modification tasks for TXT, PDF, DOCX, and XLSX formats.",
        system_message="""
        You are the File Execution Specialist.

        YOUR TASK:
        Create or edit requested output files (PDF, DOCX, XLSX, TXT) using verified data and synthesized improvements provided in the conversation context.

        CONTEXT & ATTACHMENTS:
        - Attached user files (PDFs, DOCX, XLSX, TXT, images) and chat history are AUTOMATICALLY extracted and present in your text context.

        CRITICAL ANTI-LAZINESS & ANTI-PLACEHOLDER RULES:
        - NEVER use placeholders, summaries, or shorthand in tool arguments (e.g., forbidden terms: `[Insert Original Strategy...]`, `[Placeholder: ...]`, `[TBD]`, `[TODO]`, `...`).
        - Write out EVERY single sentence, paragraph, section, header, and detail in full inside tool call parameters.
        - If generating a PDF or DOCX, populate the `sections` list with complete, expanded body text containing all ideas, strategies, and improvements discussed in the conversation.
        - If generating an Excel sheet, include every data row and cell value in full without skipping rows.

        WORKFLOW:
        1. Select the tool matching the requested output format:
           - `.txt`, `.md`, `.csv` -> `save_text_file`
           - `.pdf`               -> `create_pdf_document`
           - `.docx`              -> `create_docx_document`
           - `.xlsx`              -> `create_excel_spreadsheet`
        2. Execute the tool with FULL, non-truncated text content. All creation tools automatically target the user's `Downloads` folder.
        3. ALWAYS call `verify_file` immediately after file creation using the exact absolute path returned in the tool's SUCCESS response.
        """,
    )

    file_auditor_agent = AssistantAgent(
        name="file_auditor_agent",
        model_client=model_client,
        description="Audits file execution tasks to confirm correct generation and verification.",
        system_message="""
        You are the File Operation Auditor.

        Inspect the user's original task, the executor's tool invocation arguments, and the tool execution responses.

        VERIFICATION CHECKLIST:
        1. TOOL SELECTION & EXECUTION: Was the correct format generation tool called with complete data?
        2. STRICT ANTI-PLACEHOLDER AUDIT: Inspect the actual content passed into the tool parameters. 
           - Does the text contain any placeholders, bracketed hints, lazy shortcuts, or truncated text (e.g., `[Placeholder...]`, `[Insert...]`, `[TODO]`, `[TBD]`, `...`)?
           - IF ANY PLACEHOLDERS OR LAZY SHORTCUTS ARE DETECTED IN THE TOOL ARGUMENTS, REJECT IMMEDIATELY.
        3. FILE VERIFICATION: Was `verify_file` called on the output file path, and did it return `VERIFY_SUCCESS` with a non-zero byte size?

        RESPONSE RULES:
        If ALL criteria are satisfied with ZERO placeholders and complete text, respond exactly:

        FILE_TASK_COMPLETE

        Otherwise respond:

        FILE_TASK_INCOMPLETE
        REASON: <Specify exact issue, e.g., "Executor used placeholder [Insert...] instead of full text in section 2", or "Missing verify_file step">
        """,
    )

    termination = TextMentionTermination("FILE_TASK_COMPLETE") | MaxMessageTermination(6)

    return RoundRobinGroupChat(
        participants=[file_executor_agent, file_auditor_agent],
        name="file_execution_agent",
        description="File execution team that generates and verifies text, PDF, Word, and Excel documents.",
        termination_condition=termination,
        max_turns=6,
    )
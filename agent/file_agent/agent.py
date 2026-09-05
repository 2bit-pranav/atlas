from datetime import datetime
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.models import ChatCompletionClient
from .tools import (
    create_docx_document,
    create_excel_spreadsheet,
    create_pdf_document,
    run_python_code,
    run_terminal_command,
    save_text_file,
    verify_file,
)
from agent.skill_tools import run_skill_script

def create_file_agent(model_client: ChatCompletionClient) -> RoundRobinGroupChat:
    current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

    file_executor_agent = AssistantAgent(
        name="file_executor_agent",
        model_client=model_client,
        tools=[
            save_text_file,
            create_pdf_document,
            create_docx_document,
            create_excel_spreadsheet,
            run_python_code,
            run_terminal_command,
            run_skill_script,
            verify_file,
        ],
        description="Executes file creation, edits, dynamic Python code execution, and skill-based workflows.",
        system_message=f"""
        You are the File Execution Specialist.
        CURRENT SYSTEM DATE/TIME: {current_datetime}

        YOUR TASK:
        Create, edit, or manipulate requested output files (PDF, DOCX, XLSX, TXT) using verified data, dynamic scripts, or `@skill` manuals provided in context.

        STRICT CONTENT & ANTI-REFUSAL GUARDRAILS:
        1. REAL LOCAL EXECUTION: You possess REAL tools (`run_python_code`, `run_skill_script`, `save_text_file`, `create_pdf_document`, `create_docx_document`, `create_excel_spreadsheet`, `verify_file`).
        2. NEVER state "I cannot access local files", "As an AI model I cannot rotate PDFs", "I cannot perform file manipulation", or give LLM capability disclaimers. You MUST invoke your tools.
        3. NEVER use generic placeholders or lazy shortcuts (e.g., `[TODO]`, `[Insert content here]`, `[TBD]`, `...`) in document text or python code.
        4. Always output COMPLETE, FULLY WRITTEN text and code.

        DEPENDENCY & SKILL WORKFLOW:
        1. Read any activated `@skill` instructions (`SKILL.md`) and bundled script listings present in your prompt context.
        2. To perform operations described in a skill (e.g. rotating PDFs, merging PDFs, OCR, image extraction, form filling):
           - Use `run_skill_script(skill_name, script_path, args)` if a matching bundled script exists.
           - OR use `run_python_code(code, dependencies=[...])` to execute Python code following the skill recipes.
        3. ALWAYS use the exact `INPUT_FILE` absolute path provided in context for source files, and write outputs to absolute paths in the local Downloads directory.
        4. Resolve dependencies BEFORE executing main logic:
           - Pass required library names directly into `run_python_code(code, dependencies=['pypdf', 'pdfplumber', ...])` so `uv run` handles isolated sandbox provisioning automatically.
           - OR run pre-flight installation commands using `run_terminal_command("uv pip install <packages>")` or `run_terminal_command("pip install <packages>")`.

        SKILL & SCRIPT EXECUTION RULES:
        1. To run allowlisted scripts bundled inside an installed skill directory, use `run_skill_script(skill_name, script, args)`:
           - `skill_name`: e.g. "pdf"
           - `script`: e.g. "scripts/rotate_pdf.py" (must provide exact script path)
           - `args`: MUST be a list of positional argument strings in order, e.g. ["C:/path/input.pdf", "C:/path/output.pdf", "90", "all"]. NEVER pass a single string or flag string to args!
        2. To run dynamic custom scripts or Python logic described in a skill (such as PDF rotation using pypdf), use `run_python_code`.

        ERROR HANDLING & RECOVERY RULES:
        1. If execution tools return `[MISSING_DEPENDENCY_ERROR]`, `[SYNTAX_ERROR]`, `[PYTHON_RUNTIME_ERROR]`, `[TERMINAL_EXEC_ERROR]`, or `[FILE_ERROR]`:
           - DO NOT swallow or suppress the error traceback.
           - If it is a fixable code bug (e.g., syntax error, typo, or minor logic mistake), rewrite and retry execution ONCE via `run_python_code`.
           - If a required system binary or environment dependency fails to install or run, IMMEDIATELY halt execution and output the exact error details, missing package name, and required install command so the auditor and Atlas can report it to the user.

        FILE VERIFICATION RULE:
        1. ALWAYS call `verify_file(file_path)` on the final produced file path in your `Downloads` directory to verify non-zero byte creation before completing your turn.
        """,
    )

    file_auditor_agent = AssistantAgent(
        name="file_auditor_agent",
        model_client=model_client,
        description="Audits file execution tasks and code executions.",
        system_message=f"""
        You are the File Operation Auditor.
        CURRENT SYSTEM DATE/TIME: {current_datetime}

        REAL EXECUTION CONTEXT:
        The File Executor Agent has live execution tools (`run_python_code`, `run_skill_script`, `save_text_file`, `create_pdf_document`, etc.) to process local files, execute `@skill` workflows (including PDF rotation, merging, extraction, and script execution), and save files to disk.

        VERIFICATION CHECKLIST:
        1. Was the file/skill task executed using a tool (`run_python_code`, `run_skill_script`, etc.) without unhandled errors?
        2. If the executor outputted a capability refusal (e.g., "I cannot access local files" or "cannot rotate PDFs") instead of invoking tools, IMMEDIATELY mark the task INCOMPLETE:
           FILE_TASK_INCOMPLETE
           REASON: Executor attempted capability disclaimer instead of invoking run_python_code or run_skill_script tool.
        3. If code execution returned `[MISSING_DEPENDENCY_ERROR]`, `[PYTHON_RUNTIME_ERROR]`, or `[FILE_ERROR]`, mark the task INCOMPLETE and forward the exact traceback/message.
        4. Was `verify_file` called on the output file, returning `VERIFY_SUCCESS`?
        5. Check that no placeholder text (`[TODO]`, `[Insert...]`, `[TBD]`, `...`) remains in output parameters or generated files.

        RESPONSE RULES:
        If all criteria are satisfied and file output is verified, respond exactly:
        FILE_TASK_COMPLETE

        If execution failed, dependency was missing, or file creation failed, respond:
        FILE_TASK_INCOMPLETE
        REASON: <Detailed breakdown of failure, exact traceback, or missing dependencies>
        """,
    )

    termination = TextMentionTermination("FILE_TASK_COMPLETE") | MaxMessageTermination(6)
    return RoundRobinGroupChat(
        participants=[file_executor_agent, file_auditor_agent],
        name="file_execution_agent",
        description="Executes file operations, dynamic Python scripts, and installed skills.",
        termination_condition=termination,
        max_turns=6,
    )
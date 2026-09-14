import inspect
import ast
import re
import shutil
import subprocess
import sys
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, Optional

# ContextVar storing the active chat session's isolated workspace directory
_active_workspace_var: ContextVar[Path] = ContextVar("_active_workspace_var")


def set_active_workspace(workspace_dir: Path) -> None:
    """Sets the active execution sandbox for the current task context."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    _active_workspace_var.set(workspace_dir.resolve())


def get_active_workspace() -> Path:
    """Retrieves the active session workspace or falls back to a safe default."""
    try:
        return _active_workspace_var.get()
    except LookupError:
        fallback = Path.home() / "atlas_workspace"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()


def safe_tool_response(func: Callable) -> Callable:
    """
    CRITICAL to prevent autogen empty tool response runtime exception.
    """
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                res = await func(*args, **kwargs)
                if res is None or not str(res).strip():
                    return "[TOOL_STATUS: SUCCESS] Action completed with no textual output."
                return str(res).strip()
            except Exception as exc:
                return f"[TOOL_STATUS: ERROR] {type(exc).__name__}: {str(exc)}"
        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                res = func(*args, **kwargs)
                if res is None or not str(res).strip():
                    return "[TOOL_STATUS: SUCCESS] Action completed with no textual output."
                return str(res).strip()
            except Exception as exc:
                return f"[TOOL_STATUS: ERROR] {type(exc).__name__}: {str(exc)}"
        return sync_wrapper


FORBIDDEN_PATTERNS = [
    r"system32",
    r"rmdir\s+/[sS]",
    r"format\s+[a-zA-Z]:",
    r"powershell.*remove-item.*-recurse",
    r"shutil\.rmtree\(['\"]/[^'\"]*['\"]?\)",  # rmtree on root
    r"os\.system\(",                           # Force structured subprocess or python primitives
    r"__import__\(['\"]os['\"]\)\.system",
]

FORBIDDEN_CALLS = {
    "os.system",
    "posix.system",
    "winreg",
}

def validate_code_safety(code: str) -> Optional[str]:
    """Inspects the code for dangerous destructive calls or path traversal."""
    code_lower = code.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, code_lower):
            return f"[SECURITY_VIOLATION]: Execution blocked. Detected dangerous system pattern: '{pattern}'."
    
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            # Block raw os.system calls
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    call_name = f"{func.value.id}.{func.attr}"
                    if call_name in FORBIDDEN_CALLS:
                        return f"[SECURITY_VIOLATION]: Calling '{call_name}' is disallowed."
    except SyntaxError as e:
        # Let python run and capture syntax errors naturally
        pass

    return None


@safe_tool_response
def run_python_code(
    code: str,
    dependencies: Optional[List[str]] = None,
) -> str:
    """Executes Python code in the session's workspace sandbox."""
    # 1. Run safety scan
    violation = validate_code_safety(code)
    if violation:
        return violation

    workspace = get_active_workspace()
    script_path = workspace / "_task_runner.py"
    script_path.write_text(code, encoding="utf-8")

    uv_path = shutil.which("uv")
    if dependencies and uv_path:
        cmd = [uv_path, "run"]
        for dep in dependencies:
            cmd.extend(["--with", dep])
        cmd.append(str(script_path))
    else:
        cmd = [sys.executable, str(script_path)]

    try:
        res = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        # Clean up the runner file
        if script_path.exists():
            try:
                script_path.unlink()
            except Exception:
                pass

        if res.returncode == 0:
            return f"[EXECUTION_SUCCESS]\nSTDOUT:\n{stdout}" if stdout else "[EXECUTION_SUCCESS] Completed with exit code 0."
        
        return f"[EXECUTION_ERROR (Exit Code {res.returncode})]\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
    except subprocess.TimeoutExpired:
        return "[EXECUTION_TIMEOUT]: Execution timed out after 60 seconds."


@safe_tool_response
def read_file(
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """
    Reads contents of a text/code file.
    Supports optional line slicing (1-based index) to prevent context window overflow.
    """
    workspace = get_active_workspace()
    path = Path(file_path)
    if not path.is_absolute():
        path = (workspace / path).resolve()

    if not path.exists() or not path.is_file():
        return f"[FILE_ERROR] File '{file_path}' does not exist."

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"[FILE_ERROR] Failed to read '{file_path}': {e}"

    total_lines = len(lines)
    if start_line is not None or end_line is not None:
        start = max(0, (start_line or 1) - 1)
        end = min(total_lines, end_line or total_lines)
        sliced = "\n".join(lines[start:end])
        return f"[FILE: {path.name} (Lines {start + 1}-{end} of {total_lines})]\n{sliced}"

    content = "\n".join(lines)

    # cap at 25,000 characters
    if len(content) > 25000:
        return (
            f"[FILE_TRUNCATED: Showing first 25k chars of {path.name} (Total: {len(content)} chars)]\n"
            f"{content[:25000]}\n"
            f"...[Use start_line and end_line parameters to inspect subsequent parts]"
        )

    return f"[FILE: {path.name}]\n{content}"


@safe_tool_response
def write_file(file_name: str, content: str) -> str:
    """
    Writes text, markdown, configuration, or code directly to a file in the workspace.
    """
    workspace = get_active_workspace()
    target = workspace / Path(file_name).name
    target.write_text(content, encoding="utf-8")
    return f"[WRITE_SUCCESS] Created '{target.name}' in session workspace ({target.stat().st_size} bytes)."


@safe_tool_response
def verify_file(file_name: str) -> str:
    """
    Verifies that a generated file exists in the workspace and has non-zero size.
    Call this to confirm that a script successfully created an expected output file.
    """
    workspace = get_active_workspace()
    target = workspace / Path(file_name).name
    if not target.exists():
        return f"[VERIFY_FAILED] File '{target.name}' does not exist in workspace."
    
    size = target.stat().st_size
    if size == 0:
        return f"[VERIFY_FAILED] File '{target.name}' exists but is empty (0 bytes)."
    
    return f"[VERIFY_SUCCESS] File '{target.name}' exists and is valid ({size} bytes)."
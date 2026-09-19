"""Bounded execution tools for a single Atlas chat session."""
import ast
import inspect
import os
import re
import subprocess
import sys
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional
from server.services.settings_service import get_effective_settings

_workspace_var: ContextVar[Path] = ContextVar("atlas_workspace")
_FORBIDDEN = (
    r"system32",
    r"\bformat\s+[a-z]:",
    r"\brmdir\s+(?:/[sq]+\s+)?(?:[a-z]:\\?|\\)$",
    r"remove-item\b.*\b-recurse\b",
    r"\brm\s+-rf\s+(?:/|~|\$home)\b",
)


def safe_tool_response(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return textual tool failures instead of raising into AutoGen."""
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                result = await func(*args, **kwargs)
                return str(result).strip() or "[TOOL_STATUS: SUCCESS] Completed."
            except Exception as exc:
                return f"[TOOL_STATUS: ERROR] {type(exc).__name__}: {exc}"
        return async_wrapper

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            result = func(*args, **kwargs)
            return str(result).strip() or "[TOOL_STATUS: SUCCESS] Completed."
        except Exception as exc:
            return f"[TOOL_STATUS: ERROR] {type(exc).__name__}: {exc}"
    return wrapper


def set_active_workspace(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    _workspace_var.set(workspace_dir.resolve())


def get_active_workspace() -> Path:
    try:
        return _workspace_var.get()
    except LookupError:
        fallback = Path.cwd() / ".storage" / "unscoped-workspace"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()


def get_downloads_directory() -> Path:
    configured = get_effective_settings().system.download_directory.strip()
    downloads = (
        Path(configured).expanduser() if configured else Path.home() / "Downloads"
    )
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads.resolve()


def _is_safe_command(command: str) -> Optional[str]:
    normalized = command.lower().strip()
    if not normalized:
        return "Command must not be empty."
    if any(re.search(expression, normalized) for expression in _FORBIDDEN):
        return "Command was blocked by sandbox safety rules."
    return None


def _is_safe_python(code: str) -> Optional[str]:
    blocked = _is_safe_command(code)
    if blocked:
        return blocked
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "system"
            ):
                return "Calling os.system is blocked; use a supported tool instead."
    return None


@safe_tool_response
def run_command(command: str) -> str:
    """Run a non-destructive shell command inside this chat's workspace."""
    if problem := _is_safe_command(command):
        return f"[SECURITY_VIOLATION] {problem}"
    result = subprocess.run(
        command,
        cwd=get_active_workspace(),
        shell=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout, stderr = result.stdout.strip(), result.stderr.strip()
    if result.returncode:
        return f"[COMMAND_ERROR exit={result.returncode}]\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
    return (
        f"[COMMAND_SUCCESS]\nSTDOUT:\n{stdout}"
        if stdout
        else "[COMMAND_SUCCESS] Completed with exit code 0."
    )


@safe_tool_response
def run_python_code(code: str, dependencies: Optional[list[str]] = None) -> str:
    """Execute Python code in the workspace sandbox. Write deliverables to DOWNLOADS_DIR."""
    if problem := _is_safe_python(code):
        return f"[SECURITY_VIOLATION] {problem}"
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    preamble = (
        f"from pathlib import Path\n"
        f"DOWNLOADS_DIR = Path(r'{downloads}')\n"
        f"WORKSPACE_DIR = Path(r'{workspace}')\n"
    )
    script = workspace / "_atlas_task.py"
    script.write_text(preamble + code, encoding="utf-8")
    if dependencies:
        import shutil
        uv = shutil.which("uv")
        if not uv:
            script.unlink(missing_ok=True)
            return "[DEPENDENCY_ERROR] The uv executable is required for dynamic dependencies."
        command = [
            uv,
            "run",
            *[part for dep in dependencies for part in ("--with", dep)],
            str(script),
        ]
    else:
        command = [sys.executable, str(script)]
    env = {
        **os.environ,
        "DOWNLOADS_DIR": str(downloads),
        "WORKSPACE_DIR": str(workspace),
    }
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        script.unlink(missing_ok=True)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode:
        return f"[PYTHON_ERROR exit={result.returncode}]\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
    return f"[PYTHON_SUCCESS]\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"


@safe_tool_response
async def ask_question(question: str) -> str:
    """Ask the user a clarification question and await their answer."""
    from server.stores.interaction_registry import request_user_input
    answer = await request_user_input(question)
    return f"[USER_RESPONSE]: {answer}"


@safe_tool_response
def finish(summary: str, files_created: list[str]) -> str:
    """Mandatory completion gate. Verifies all deliverables exist in Downloads."""
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    failures: list[str] = []
    verified: list[str] = []

    for name in files_created:
        p = Path(name)
        target = p.resolve() if p.is_absolute() else (downloads / p.name).resolve()

        if target.is_file() and target.stat().st_size > 0:
            verified.append(str(target))
        else:
            ws_target = (workspace / p.name).resolve()
            if ws_target.is_file() and ws_target.stat().st_size > 0:
                failures.append(
                    f"'{p.name}' was created in internal workspace instead of Downloads. "
                    f"Write deliverables to DOWNLOADS_DIR directly (e.g. DOWNLOADS_DIR / '{p.name}')."
                )
            else:
                failures.append(f"'{name}' is missing or empty")

    if failures:
        return f"[FINISH_REJECTED] Deliverable validation failed:\n- " + "\n- ".join(failures)

    return f"[FINISH_SUCCESS] {summary}\nVerified deliverables in Downloads: {', '.join(verified) if verified else 'none'}"
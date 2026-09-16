"""Bounded execution tools for a single Atlas chat session."""

import ast
import csv
import inspect
import re
import shutil
import subprocess
import sys
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from server.services.settings_service import get_effective_settings

_workspace_var: ContextVar[Path] = ContextVar("atlas_workspace")
_DELIVERABLE_SUFFIXES = {".xlsx", ".pdf", ".docx", ".csv", ".png"}
_FORBIDDEN = (r"system32", r"\bformat\s+[a-z]:", r"\brmdir\s+(?:/[sq]+\s+)?(?:[a-z]:\\?|\\)$", r"remove-item\b.*\b-recurse\b", r"\brm\s+-rf\s+(?:/|~|\$home)\b")


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
    downloads = Path(configured).expanduser() if configured else Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads.resolve()


def _safe_filename(file_name: str) -> Path:
    name = Path(file_name).name
    if not name or name in {".", ".."}:
        raise ValueError("A plain file name is required.")
    return Path(name)


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
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "system":
                return "Calling os.system is blocked; use a supported tool instead."
    return None


def _sync_deliverables(workspace: Path, downloads: Path) -> list[Path]:
    copied: list[Path] = []
    for candidate in workspace.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in _DELIVERABLE_SUFFIXES:
            continue
        target = downloads / candidate.name
        if candidate.resolve() != target.resolve():
            shutil.copy2(candidate, target)
        copied.append(target)
    return copied


@safe_tool_response
def run_command(command: str) -> str:
    """Run a non-destructive shell command inside this chat's workspace."""
    if problem := _is_safe_command(command):
        return f"[SECURITY_VIOLATION] {problem}"
    result = subprocess.run(command, cwd=get_active_workspace(), shell=True, capture_output=True, text=True, timeout=120)
    stdout, stderr = result.stdout.strip(), result.stderr.strip()
    if result.returncode:
        return f"[COMMAND_ERROR exit={result.returncode}]\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}"
    return f"[COMMAND_SUCCESS]\nSTDOUT:\n{stdout}" if stdout else "[COMMAND_SUCCESS] Completed with exit code 0."


@safe_tool_response
def run_python_code(code: str, dependencies: Optional[list[str]] = None) -> str:
    """Execute Python in the workspace and copy generated deliverables to Downloads."""
    if problem := _is_safe_python(code):
        return f"[SECURITY_VIOLATION] {problem}"
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    script = workspace / "_atlas_task.py"
    script.write_text(f"from pathlib import Path\nDOWNLOADS_DIR = Path(r'{downloads}')\n" + code, encoding="utf-8")
    command = [sys.executable, str(script)]
    if dependencies:
        uv = shutil.which("uv")
        if not uv:
            return "[DEPENDENCY_ERROR] The uv executable is required for dynamic dependencies."
        command = [uv, "run", *[part for dependency in dependencies for part in ("--with", dependency)], str(script)]
    try:
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=120)
    finally:
        script.unlink(missing_ok=True)
    copied = _sync_deliverables(workspace, downloads)
    files = ", ".join(str(path) for path in copied) or "none"
    if result.returncode:
        return f"[PYTHON_ERROR exit={result.returncode}]\nSTDERR:\n{result.stderr.strip()}\nSTDOUT:\n{result.stdout.strip()}\nFILES: {files}"
    return f"[PYTHON_SUCCESS]\nSTDOUT:\n{result.stdout.strip()}\nSTDERR:\n{result.stderr.strip()}\nFILES: {files}"


@safe_tool_response
def write_file(file_name: str, content: str) -> str:
    target = get_downloads_directory() / _safe_filename(file_name)
    target.write_text(content, encoding="utf-8")
    return f"[WRITE_SUCCESS] Created {target} ({target.stat().st_size} bytes)."


@safe_tool_response
def verify_file(file_name: str) -> str:
    target = get_downloads_directory() / _safe_filename(file_name)
    if not target.is_file():
        return f"[VERIFY_FAILED] {target.name} does not exist in Downloads."
    if target.stat().st_size == 0:
        return f"[VERIFY_FAILED] {target.name} is empty."
    if target.suffix.lower() == ".csv":
        with target.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            if len(list(csv.reader(handle))) < 2:
                return f"[VERIFY_FAILED] {target.name} has no data rows."
    elif target.suffix.lower() == ".xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(target, read_only=True, data_only=True)
        rows = sum(1 for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True) if any(cell is not None for cell in row))
        workbook.close()
        if rows < 2:
            return f"[VERIFY_FAILED] {target.name} has no data rows."
    return f"[VERIFY_SUCCESS] {target} exists and is valid ({target.stat().st_size} bytes)."


@safe_tool_response
def finish(summary: str, files_created: list[str]) -> str:
    failures = [name for name in files_created if not verify_file(name).startswith("[VERIFY_SUCCESS]")]
    if failures:
        return f"[FINISH_BLOCKED] Unverified files: {', '.join(failures)}"
    return f"[FINISH_SUCCESS] {summary}\nVerified files: {', '.join(files_created) if files_created else 'none'}"

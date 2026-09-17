"""Safe, bounded filesystem primitives for the Atlas workspace and Downloads."""

from pathlib import Path
from typing import Optional

from server.stores.interaction_registry import request_permission

from .sandbox import get_active_workspace, get_downloads_directory, safe_tool_response

_DEFAULT_WINDOW = 250


def _resolve_target_path(file_path: str, default_to_downloads: bool = True) -> Path:
    """Resolve destination path. Deliverables default to Downloads unless workspace is explicit."""
    requested = Path(file_path).expanduser()
    workspace = get_active_workspace()
    downloads = get_downloads_directory()

    if requested.is_absolute():
        return requested.resolve()

    parts = requested.parts
    if not parts:
        return downloads.resolve()

    first = parts[0].lower().strip("/\\")
    if first in ("workspace", ".workspace", "workspace_dir"):
        sub = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        return (workspace / sub).resolve()

    if first in ("downloads", "download", "downloads_dir", "$downloads"):
        sub = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        return (downloads / sub).resolve()

    if default_to_downloads:
        return (downloads / requested).resolve()
    return (workspace / requested).resolve()


def _find_existing_file(file_path: str) -> Optional[Path]:
    """Find an existing file in Downloads or workspace."""
    requested = Path(file_path).expanduser()
    workspace = get_active_workspace()
    downloads = get_downloads_directory()

    if requested.is_absolute():
        p = requested.resolve()
        return p if p.is_file() else None

    parts = requested.parts
    if parts:
        first = parts[0].lower().strip("/\\")
        if first in ("workspace", ".workspace", "workspace_dir"):
            p = (workspace / Path(*parts[1:])).resolve()
            return p if p.is_file() else None
        if first in ("downloads", "download", "downloads_dir", "$downloads"):
            p = (downloads / Path(*parts[1:])).resolve()
            return p if p.is_file() else None

    # Check Downloads first (where deliverables live)
    cand_dl = (downloads / requested).resolve()
    if cand_dl.is_file():
        return cand_dl

    # Then check workspace
    cand_ws = (workspace / requested).resolve()
    if cand_ws.is_file():
        return cand_ws

    return None


@safe_tool_response
def view_file(
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """Read a file with 1-based line numbers and windowed output (default 250 lines)."""
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    path = _find_existing_file(file_path)
    if path is None:
        return f"[FILE_ERROR] '{file_path}' does not exist in Downloads or the session workspace."

    if not any(path.is_relative_to(root) for root in (workspace, downloads)):
        return "[FILE_ERROR] Reads are limited to this session workspace and Downloads."

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    actual_start = max((start_line or 1) - 1, 0)
    if end_line is not None:
        actual_end = min(end_line, total)
    else:
        actual_end = min(actual_start + _DEFAULT_WINDOW, total)
    header = f"--- START OF FILE WINDOW: {path.name} (Lines {actual_start + 1}-{actual_end} of {total}) ---"
    body = "\n".join(
        f"{actual_start + i + 1:5d} | {line}"
        for i, line in enumerate(lines[actual_start:actual_end])
    )
    remaining = total - actual_end
    if remaining > 0:
        footer = f"--- END OF FILE WINDOW ({remaining} lines below). Call view_file(..., start_line={actual_end + 1}) to inspect further. ---"
    else:
        footer = "--- END OF FILE ---"
    return f"{header}\n{body}\n{footer}"


@safe_tool_response
def create_file(file_path: str, content: str) -> str:
    """Write full text or code to a file. Relative paths save to Downloads by default."""
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    path = _resolve_target_path(file_path, default_to_downloads=True)

    if not any(path.is_relative_to(root) for root in (workspace, downloads)):
        return f"[FILE_ERROR] Writes are limited to the session workspace and Downloads. Got: {path}"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    lines = content.splitlines()
    loc = "Downloads" if path.is_relative_to(downloads) else "workspace"
    return f"[CREATE_SUCCESS] {path.name} created in {loc} at {path} ({len(lines)} lines, {path.stat().st_size} bytes)."


@safe_tool_response
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Surgical single-occurrence string replacement inside a file."""
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    path = _find_existing_file(file_path)
    if path is None:
        return f"[FILE_ERROR] '{file_path}' does not exist in Downloads or the session workspace."

    if not any(path.is_relative_to(root) for root in (workspace, downloads)):
        return "[FILE_ERROR] Edits are limited to this session workspace and Downloads."

    text = path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return f"[EDIT_REJECTED] old_string not found in {path.name}. Verify the exact text."
    if count > 1:
        return f"[EDIT_REJECTED] old_string found {count} times in {path.name}. Provide a more specific old_string to ensure a unique match."
    new_text = text.replace(old_string, new_string, 1)
    path.write_text(new_text, encoding="utf-8")
    return f"[EDIT_SUCCESS] Replaced 1 occurrence in {path.name}."


@safe_tool_response
async def list_directory(directory_path: str = ".") -> str:
    """List directory entries. Workspace/Downloads auto-approved; host paths require permission."""
    requested = Path(directory_path).expanduser()
    workspace, downloads = get_active_workspace(), get_downloads_directory()

    raw_lower = directory_path.lower().strip("/\\")
    if raw_lower in ("downloads", "download", "downloads_dir", "$downloads"):
        path = downloads
    elif raw_lower in ("workspace", ".workspace", "workspace_dir"):
        path = workspace
    elif not requested.is_absolute():
        path = (workspace / requested).resolve()
    else:
        path = requested.resolve()

    auto_approved = any(path.is_relative_to(root) for root in (workspace, downloads))
    if not auto_approved:
        allowed = await request_permission(
            "list_directory",
            str(path),
            {"reason": "Listing a directory outside the session workspace"},
        )
        if not allowed:
            return f"[PERMISSION_DENIED] User denied access to '{path}'. Adapt your execution plan without this folder."
    if not path.exists():
        return f"[DIR_ERROR] Path does not exist: {path}"
    if not path.is_dir():
        return f"[DIR_ERROR] Path is not a directory: {path}"
    entries = []
    for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.is_dir():
            entries.append(f"[DIR]  {item.name}/")
        else:
            size = item.stat().st_size
            entries.append(f"[FILE] {item.name} ({size:,} bytes)")
    if not entries:
        return f"[DIR_EMPTY] {path} is empty."
    return f"Directory: {path}\n" + "\n".join(entries)

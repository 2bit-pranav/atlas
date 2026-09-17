"""Safe, bounded reads from a chat workspace or its Downloads deliverables."""

from pathlib import Path
from typing import Optional

from .sandbox import get_active_workspace, get_downloads_directory, safe_tool_response


@safe_tool_response
def read_file(
    file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
) -> str:
    """Read up to 25,000 characters from the workspace or Downloads directory."""
    requested = Path(file_path).expanduser()
    workspace, downloads = get_active_workspace(), get_downloads_directory()
    path = (
        (workspace / requested).resolve()
        if not requested.is_absolute()
        else requested.resolve()
    )
    if not any(path.is_relative_to(root) for root in (workspace, downloads)):
        return "[FILE_ERROR] Reads are limited to this session workspace and Downloads."
    if not path.is_file():
        return f"[FILE_ERROR] {file_path} does not exist."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    first, last = max((start_line or 1) - 1, 0), min(end_line or len(lines), len(lines))
    content = "\n".join(lines[first:last])
    if len(content) > 25_000:
        content = content[:25_000] + "\n[TRUNCATED at 25,000 characters]"
    return f"[FILE: {path.name}, lines {first + 1}-{last} of {len(lines)}]\n{content}"

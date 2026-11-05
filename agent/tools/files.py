"""File operations: `delete_file`, `copy_file`, `move_file`.

Copying and moving never replace an existing file. `delete_file` is the one
way the agent deletes, and always to the Recycle Bin.

The permission grid (safety/grid.py) decides first: in the chat's workspace it
runs, in the user's folders it asks, Atlas's own files and system folders are
refused. Deleting with a shell command outside the workspace is refused and
pointed here, so even an approved delete can be undone from the Recycle Bin.
"""

from __future__ import annotations

import ctypes
import shutil
import sys
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any

from strands import tool


def _failed(message: str) -> dict[str, Any]:
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


_FO_DELETE = 0x3
#: Undo (the Recycle Bin), and no dialogs: the user already agreed on the approval card.
_FLAGS = 0x40 | 0x10 | 0x4 | 0x400   # FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI


def recycle(path: Path) -> None:
    """Move a file or folder to the Recycle Bin. Raises OSError when it did not happen."""
    if sys.platform != "win32":
        raise OSError("the Recycle Bin is only used on Windows")
    op = _SHFILEOPSTRUCTW(wFunc=_FO_DELETE, pFrom=str(path.resolve()) + "\0", fFlags=_FLAGS)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted or path.exists():
        raise OSError(f"Windows could not move it to the Recycle Bin (code {code})")


def file_tools(resolve: Callable[[str], Path], shown: Callable[[Path], str]) -> list[Any]:
    @tool(name="delete_file")
    def delete_file(path: str) -> Any:
        """Delete a file or folder by moving it to the Recycle Bin, so it can be restored.

        Deleting the user's files asks them first. Never delete with a shell command.

        Args:
            path: The file or folder: a name in your workspace, or its full path.
        """
        target = resolve(path)
        if not target.exists():
            return _failed(f"no file or folder {target.name} at {shown(target)}.")
        try:
            recycle(target)
        except OSError as exc:
            return _failed(f"could not delete {target.name}: {exc}")
        return f"Moved {shown(target)} to the Recycle Bin. The user can restore it from there."

    def _pair(path: str, destination: str) -> tuple[Path, Path] | dict[str, Any]:
        source, target = resolve(path), resolve(destination)
        if not source.exists():
            return _failed(f"no file or folder {source.name} at {shown(source)}. find_files can find it.")
        if target.is_dir():                       # into a folder, keeping the name
            target = target / source.name
        if target.exists():
            # Never over another file: that would lose it with no way back.
            return _failed(f"{shown(target)} already exists. Choose another name; nothing was changed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return source, target

    @tool(name="copy_file")
    def copy_file(path: str, destination: str) -> Any:
        """Copy a file or folder. Never replaces an existing file.

        Args:
            path: The file or folder to copy.
            destination: The new path, or a folder to copy it into.
        """
        pair = _pair(path, destination)
        if isinstance(pair, dict):
            return pair
        source, target = pair
        try:
            (shutil.copytree if source.is_dir() else shutil.copy2)(source, target)
        except OSError as exc:
            return _failed(f"could not copy {source.name}: {exc}")
        return f"Copied {shown(source)} to {shown(target)}."

    @tool(name="move_file")
    def move_file(path: str, destination: str) -> Any:
        """Move or rename a file or folder. Never replaces an existing file.

        Args:
            path: The file or folder to move.
            destination: The new path (a new name renames it), or a folder to move it into.
        """
        pair = _pair(path, destination)
        if isinstance(pair, dict):
            return pair
        source, target = pair
        try:
            shutil.move(str(source), str(target))
        except OSError as exc:
            return _failed(f"could not move {source.name}: {exc}")
        return f"Moved {shown(source)} to {shown(target)}."

    return [delete_file, copy_file, move_file]


__all__ = ["file_tools", "recycle"]

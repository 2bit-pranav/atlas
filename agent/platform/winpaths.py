"""Path forms on Windows: the `/c/Users/...` form shown to the model, the
`C:/Users/...` form Python needs, and finding Git Bash."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

#: Where Git for Windows puts a POSIX shell. Checked because the executable has
#: to be findable by `CreateProcess`, which searches the calling process's PATH
#: rather than any environment handed to the child -- see `_find_posix_shell`.
GIT_BIN_CANDIDATES = (
    Path(r"C:\Program Files\Git\bin"),
    Path(r"C:\Program Files (x86)\Git\bin"),
    Path.home() / "AppData" / "Local" / "Programs" / "Git" / "bin",
)


# ----------------------------------------------------------------- paths --

_MSYS = re.compile(r"^/([A-Za-z])(?:/|$)(.*)$")


_SLASH_DRIVE = re.compile(r"^/([A-Za-z]):[/\\]?(.*)$")


def drive_path(path: str) -> str:
    """`/c/Users/x` or `/C:/Users/x` -> `C:/Users/x`; anything else unchanged.

    Only the drive forms, never other POSIX paths: used on MCP arguments,
    where a string that merely starts with `/` may be a URL path or a pattern.
    """
    if sys.platform != "win32" or not path.startswith("/"):
        return path
    for pattern in (_SLASH_DRIVE, _MSYS):
        if (m := pattern.match(path)) is not None:
            return f"{m.group(1).upper()}:/{m.group(2)}"
    return path


def windows_path(path: str) -> str:
    """`/c/Users/x` or `/C:/Users/x` -> `C:/Users/x`. Anything else unchanged."""
    if sys.platform != "win32":
        return path
    for pattern in (_SLASH_DRIVE, _MSYS):
        if (m := pattern.match(path)) is not None:
            return f"{m.group(1).upper()}:/{m.group(2)}"
    if path.startswith("/") and not path.startswith("//"):
        # Any other POSIX path (`/tmp/...`, `/usr/...`) means what Git Bash
        # says it means: resolved naively, `/tmp/x` became `C:\tmp\x`, which
        # does not exist.
        if (mapped := _cygpath(path)) is not None:
            return mapped
    return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)


def _cygpath(path: str) -> str | None:
    shell = _find_posix_shell_cached()
    if shell is None:
        return None
    # The shell may have been found in Git's `bin` or in `usr/bin` itself.
    exe = next((p for p in (shell / "cygpath.exe", shell.parent / "usr" / "bin" / "cygpath.exe")
                if p.is_file()), None)
    if exe is None:
        return None
    import subprocess

    try:
        out = subprocess.run([str(exe), "-w", path], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def model_path(path: str | Path) -> str:
    """How a path is written when the model is told about it.

    On Windows with Git Bash: `/c/Users/...`. That one form works in all three
    places a model uses a path -- unquoted in bash (a backslash there is an
    escape, which dropped every separator from a Windows path), as an argument to
    a native program (MSYS converts it to `C:/Users/...` for python.exe), and
    in the harness file tools, which demand a leading `/`.
    """
    p = Path(path).resolve()
    if sys.platform != "win32":
        return str(p)
    posix = p.as_posix()
    if _find_posix_shell_cached() is None:
        return f"/{posix}"  # `/C:/...`: still passes the file tools' check
    drive, _, rest = posix.partition(":/")
    return f"/{drive.lower()}/{rest}"


#: The chat's workspace as the model may write it: in every tool, the policy's
#: checks and the shell (where it is an environment variable).
_WORKSPACE_VAR = re.compile(r"^(?:\$ATLAS_WORKSPACE|\$\{ATLAS_WORKSPACE\}|%ATLAS_WORKSPACE%)(?=$|[/\\])")


def expand_workspace(raw: str, workspace: Path) -> str:
    """`$ATLAS_WORKSPACE/x` as the workspace's own path; anything else unchanged."""
    return _WORKSPACE_VAR.sub(lambda _m: Path(workspace).as_posix(), raw)


def shown_in(workspace: Path):
    """How a chat shows the model a path: a file in the workspace by its name (the
    tools find it there), the workspace itself as `$ATLAS_WORKSPACE`, anything else
    in full. The workspace's own path holds a 32-character chat id, which the model
    copied wrong and landed in another chat's folder (2026-11-05)."""
    ws = Path(workspace).resolve()

    def shown(path: str | Path) -> str:
        p = Path(path).resolve()
        if p == ws:
            return "$ATLAS_WORKSPACE"
        return p.relative_to(ws).as_posix() if ws in p.parents else model_path(p)
    return shown


_shell_cache: list[Path | None] = []


def _find_posix_shell_cached() -> Path | None:
    if not _shell_cache:
        _shell_cache.append(_find_posix_shell())
    return _shell_cache[0]


# ------------------------------------------------------- shell discovery --


def _find_posix_shell() -> Path | None:
    """Locate a POSIX shell and put it where `CreateProcess` will find it.

    Returns the directory to prepend to PATH, or None if there is no POSIX shell
    and the caller should fall back to `cmd.exe`.

    **PATH has to be changed process-wide.** Windows resolves an executable
    against the *calling* process's PATH; the environment passed to a child is
    consulted only after the image is found. Measured: with Git's `bin` on
    `env["PATH"]` every call still failed with `WinError 2`. `os.environ` is
    the only lever.
    """
    candidates: list[Path] = []
    found = shutil.which("sh") or shutil.which("bash")
    if found:
        candidates.append(Path(found).parent)
    candidates.extend(GIT_BIN_CANDIDATES)

    for directory in candidates:
        if not ((directory / "sh.exe").is_file() or (directory / "sh").is_file()):
            continue
        # Both directories: `bin` holds only the shells and `git.exe`; `ls`,
        # `grep`, `sed`, `find` and the rest live in `usr/bin`. With only `bin`
        # on PATH the shell starts, then every command is "not found".
        _prepend_path(directory)
        sibling = directory.parent / "usr" / "bin"
        if sibling.is_dir():
            _prepend_path(sibling, last=True)
        return directory
    return None


def _prepend_path(directory: Path, *, last: bool = False) -> None:
    """Put `directory` on this process's PATH, once.

    `last=True` appends instead of prepending, for the Git `usr/bin` entry that
    must not outrank the venv's `Scripts` directory -- `python` has to be the
    project interpreter, and `usr/bin` has no `python` but might gain one.
    """
    entry = str(directory)
    lowered = entry.lower()
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    parts = [p for p in parts if p.lower() != lowered]
    os.environ["PATH"] = os.pathsep.join(
        parts + [entry] if last else [entry] + parts
    )


__all__ = ["GIT_BIN_CANDIDATES", "drive_path", "expand_workspace", "model_path", "shown_in", "windows_path"]

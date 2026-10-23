"""A Windows execution environment for the harness `shell` tool.

**Why it exists.** Strands' default "no sandbox" environment runs every
command as `sh -c <command>`. There is no `sh` on Windows, so every shell call
failed with `[WinError 2] The system cannot find the file specified`, and
every skill is "run a script through `shell`".

This subclasses the stock local environment. File reads, writes, listing and
removal are inherited unchanged; command execution and path resolution are
overridden. Nothing in Strands is patched.

**Which shell it uses.** Git Bash when it can be found, so the stock
implementation runs unmodified and the quoting in every `SKILL.md` behaves as
written. The `cmd.exe` fallback needs three workarounds: a one-shot batch file
(Windows re-quotes `argv`, breaking `python -c "..."`), `skills/_shared.py`'s
`unquote` (`cmd` leaves quotes attached to a path) and `join_sql` (`cmd`
splits a quoted SQL statement on its spaces). The last two also make the
scripts tolerant of a small model's mangled quoting.

**What it is not.** A security boundary. Commands run on the host with the
backend's own privileges. Working in the chat's workspace folder is a
working-directory convention, not a sandbox.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, AsyncGenerator

from strands.sandbox.base import ExecutionResult, StreamChunk
from strands.sandbox.errors import SandboxTimeoutError
from strands.sandbox.posix_shell import build_shell_env_prefix
from strands.sandbox.not_a_sandbox_local_environment import (
    NotASandboxLocalEnvironment,
)

#: The only language `execute_code` runs. It runs with `sys.executable`, the
#: backend's own interpreter, which has the venv's packages.
DEFAULT_CODE_LANGUAGE = "python"

#: Where Git for Windows puts a POSIX shell. Checked because the executable has
#: to be findable by `CreateProcess`, which searches the calling process's PATH
#: rather than any environment handed to the child -- see `_find_posix_shell`.
GIT_BIN_CANDIDATES = (
    Path(r"C:\Program Files\Git\bin"),
    Path(r"C:\Program Files (x86)\Git\bin"),
    Path.home() / "AppData" / "Local" / "Programs" / "Git" / "bin",
)

#: A legal POSIX shell variable name. Anything else cannot be `export`ed, and
#: Strands validates the environment it is asked to pass (`validate_env_keys`),
#: so an inherited Windows name like `PROGRAMFILES(X86)` raises rather than
#: warns. Two such names exist on a typical machine; this is why the POSIX path
#: never forwards the raw environment.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class WindowsLocalEnvironment(NotASandboxLocalEnvironment):
    """A POSIX shell where one exists, `cmd.exe` where one does not."""

    def __init__(self, cwd: Path | None = None, skills: Path | None = None,
                 folders: list[Path] | None = None) -> None:
        self.shell_dir = _find_posix_shell()
        #: Where commands run unless told otherwise: the chat's workspace. The
        #: model then names an attached file `"exp4.pdf"`, not a path holding
        #: a 32-character chat id -- which it once copied as `a34a34a3...`.
        self.cwd = Path(cwd) if cwd else None
        if self.cwd:
            self.cwd.mkdir(parents=True, exist_ok=True)
        #: `$ATLAS_SKILLS` in every command, so a SKILL.md can name its script
        #: wherever the command runs from.
        self.extra_env = {"ATLAS_SKILLS": model_path(skills)} if skills else {}
        #: The allowed folders, where a relative path is looked for after the
        #: workspace (`locate`). Scripts get them as `$ATLAS_FOLDERS`.
        self.folders = list(folders or [])
        #: The agent's cancel signal (`agent_factory` sets it): Stop ends a
        #: running command too, not only the model's turn.
        self.cancel_signal: threading.Event | None = None
        if self.folders:
            self.extra_env["ATLAS_FOLDERS"] = os.pathsep.join(str(f) for f in self.folders)

    def _env(self, env: dict[str, str] | None) -> dict[str, str]:
        return {**self.extra_env, **(env or {})}

    def _resolve_path(self, path: str) -> Path:
        """Accept the path forms a model sees on this machine.

        The harness file tools reject any path that does not start with `/`, so
        a Windows drive path can never reach them. The model is
        therefore shown Git-Bash paths (`/c/Users/...`, see `model_path`),
        which pass that check, work unchanged in the shell, and are converted
        here for Python's own file calls. `/C:/Users/...` is accepted too,
        because a model given one form will sometimes produce the other. A
        relative path is looked for in the workspace, then in the allowed
        folders (`locate`).
        """
        if not path.startswith("/") and not os.path.isabs(path) and self.cwd is not None:
            return locate(path, self.cwd, self.folders) or self.cwd / path
        return Path(windows_path(path))

    # ------------------------------------------------------------ execution --

    async def execute_streaming(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        cwd = cwd or (str(self.cwd) if self.cwd else None)
        env = self._env(env)
        try:
            if self.shell_dir is not None:
                async for chunk in self._posix(command, timeout=timeout, cwd=cwd, env=env):
                    yield chunk
                return

            async for chunk in self._cmd(command, timeout=timeout, cwd=cwd, env=env):
                yield chunk
        except SandboxTimeoutError:
            raise  # the shell tool reports it, with the output so far
        except Exception as exc:
            loop_name = type(asyncio.get_running_loop()).__name__
            yield ExecutionResult(
                stdout="",
                stderr=f"Shell execution failed [{type(exc).__name__}: {exc}] (loop={loop_name}, cwd={cwd or os.getcwd()})",
                exit_code=1,
            )
    
    async def _posix(
        self,
        command: str,
        *,
        timeout: float | None,
        cwd: str | None,
        env: dict[str, str] | None,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        """`sh -c` in the workspace, as Strands runs it, but stoppable.

        Strands' own runner kills the process only when the task consuming it
        is cancelled, and Stop cancels no task; on Windows it would kill only
        `sh.exe` anyway. A 67-page OCR read went on for minutes after Stop.
        Here the command's whole process tree is ended on Stop or timeout.
        """
        full = f"cd {shlex.quote(cwd or os.getcwd())} && {build_shell_env_prefix(_posix_env(env))}{command}"
        process = await asyncio.create_subprocess_exec(
            "sh", "-c", full, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        yield await self._finish(process, timeout)

    async def _finish(self, process: asyncio.subprocess.Process, timeout: float | None) -> ExecutionResult:
        """Wait for a command; on Stop or after `timeout` (default 120 s), kill its
        whole process tree and report what it printed so far."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (timeout or 120.0)
        work = asyncio.ensure_future(process.communicate())
        stopped = False
        while not work.done():
            await asyncio.wait({work}, timeout=0.25)
            if work.done():
                break
            stopped = self.cancel_signal is not None and self.cancel_signal.is_set()
            if stopped or loop.time() > deadline:
                _kill_tree(process)
                try:
                    await asyncio.wait_for(asyncio.shield(work), 10)
                except asyncio.TimeoutError:
                    work.cancel()
                break
        stdout, stderr = (_decode(b) for b in work.result()) if work.done() and not work.cancelled() else ("", "")
        if stopped:
            return ExecutionResult(stdout=stdout, stderr=(stderr + "\nStopped by the user.").strip(), exit_code=130)
        if process.returncode is None or loop.time() > deadline:
            raise SandboxTimeoutError(timeout or 120.0, stdout=stdout, stderr=stderr)
        return ExecutionResult(stdout=stdout, stderr=stderr, exit_code=process.returncode)

    async def _cmd(
        self,
        command: str,
        *,
        timeout: float | None,
        cwd: str | None,
        env: dict[str, str] | None,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        """The fallback: `cmd /c <one-shot batch file>`.

        A batch file rather than the command in `argv`. As an argument, Python
        joins argv back into a command line and wraps an already-quoted command
        again, and `cmd` strips only the *outer* pair, leaving the inner quotes
        as literal characters: `python -c "import sys"` failed with
        `SyntaxError: unterminated string literal`. A batch file runs the
        command exactly as if typed at a prompt.
        """
        argv, shell_name, batch = _cmd_argv(command)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=_cmd_env(env),
            )
        except FileNotFoundError as exc:  # pragma: no cover - defensive
            _discard(batch)
            raise RuntimeError(
                f"cannot launch {shell_name}: {exc}. No POSIX shell was found "
                "and cmd.exe is not on PATH either."
            ) from exc

        try:
            result = await self._finish(process, timeout)
        finally:
            # Deleted whatever happened, including a timeout, so one .cmd per
            # tool call does not accumulate.
            _discard(batch)
        yield result

    async def execute(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Collect the streamed output and return it whole."""
        chunks: list[StreamChunk | ExecutionResult] = []
        async for chunk in self.execute_streaming(
            command, timeout=timeout, cwd=cwd, env=env, **kwargs
        ):
            chunks.append(chunk)
        for chunk in reversed(chunks):
            if isinstance(chunk, ExecutionResult):
                return chunk
        return ExecutionResult(stdout="", stderr="", exit_code=1)

    async def execute_code(
        self,
        code: str,
        language: str = DEFAULT_CODE_LANGUAGE,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Pipe code to the interpreter rather than through a shell.

        Only the language this project actually uses is supported. Everything
        else is refused rather than guessed at, because the POSIX and `cmd`
        code paths disagree about what `-c` means for a shell that is not
        Python, and a script that silently does something else is worse than one
        that says no.
        """
        language = (language or DEFAULT_CODE_LANGUAGE).lower()
        if language not in ("python", "py"):
            return ExecutionResult(
                stdout="",
                stderr=f"only python is supported by execute_code, not {language!r}",
                exit_code=2,
            )

        # `sys.executable`, never a bare `python`, so the code runs with the
        # venv's packages whatever PATH says.
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or (str(self.cwd) if self.cwd else None),
            env=_cmd_env(self._env(env)),
        )
        return await self._finish(process, timeout)

    async def execute_code_streaming(
        self,
        code: str,
        language: str = DEFAULT_CODE_LANGUAGE,
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        yield await self.execute_code(
            code, language, timeout=timeout, cwd=cwd, env=env, **kwargs
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
        # says it means. web_fetch has curl write to `/tmp/strands-web-fetch-*`
        # and then reads it back; resolved naively that became `C:\tmp\...`,
        # which does not exist, and every fetch failed.
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


# -------------------------------------------------------------- environment --


def _venv_first(env: dict[str, str] | None) -> dict[str, str]:
    """The environment, with the venv's `Scripts` directory first on PATH.

    Every skill script is run as a bare `python ...` and needs the venv's
    packages, but the *system* Python comes first on PATH, so the scripts
    failed with `No module named 'duckdb'`. Telling the model to use
    `sys.executable` did not work (it wrote `python` anyway, then pip-installed
    into user site-packages), and a `python.bat` shim shadows a deliberate
    `python` elsewhere. Putting the real interpreter first needs no cooperation
    from the model.

    Derived from `sys.executable` so it cannot drift from the interpreter that
    is running. `VIRTUAL_ENV` is set too, so `python -m ...` agrees.
    """
    merged = {**os.environ, **(env or {})}
    scripts = Path(sys.executable).resolve().parent
    if not (scripts / "python.exe").is_file():
        return merged

    parts = [p for p in merged.get("PATH", "").split(os.pathsep) if p]
    normalised = {p.lower().replace("\\", "/") for p in parts}
    if scripts.as_posix().lower() not in normalised:
        parts.insert(0, str(scripts))
    merged["PATH"] = os.pathsep.join(parts) if parts else str(scripts)
    merged.setdefault("VIRTUAL_ENV", str(scripts.parent))
    # Skill scripts print document text, which is full of characters cp1252
    # cannot encode. UTF-8 mode makes their stdout safe whatever the console.
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    return merged


def _posix_env(env: dict[str, str] | None) -> dict[str, str]:
    """The environment a POSIX shell can actually accept.

    Drops the inherited Windows variables whose *names* are illegal POSIX
    identifiers -- `PROGRAMFILES(X86)` and `COMMONPROGRAMFILES(X86)` on a
    typical machine. Strands validates what it is asked to export and raises on
    them, so passing `os.environ` through unfiltered turns every shell call into
    a `ValueError`.

    A legal name with a Windows-shaped value is kept; the shell passes it
    through untouched.

    **PATH is re-joined with `:` rather than `;`.** Measured: with a
    semicolon-separated PATH bash found its own tools but silently not
    `python`. MSYS translates the value back to Windows form for native
    children, so the venv's `python.exe` still runs with its packages.
    """
    merged = _venv_first(env)
    legal = {k: v for k, v in merged.items() if _ENV_NAME.fullmatch(k)}
    if "PATH" in legal:
        legal["PATH"] = ":".join(p for p in legal["PATH"].split(os.pathsep) if p)
    return legal


def _cmd_env(env: dict[str, str] | None) -> dict[str, str]:
    """Windows has no name restrictions, so the full environment goes through."""
    return _venv_first(env)


# ------------------------------------------------------------------ helpers --


def _cmd_argv(command: str) -> tuple[list[str], str, str | None]:
    """`cmd /c <batch file>`, or `powershell -Command <command>` as a fallback.

    The path is returned bare, not quoted: `create_subprocess_exec` rebuilds the
    command line itself and adds quotes only where needed, and pre-quoting here
    made it emit `\"C:\\...\\x.cmd\"`, which `cmd` reads as a command name that
    begins with a literal quote and is therefore not recognised.
    """
    cmd = shutil.which("cmd.exe") or shutil.which("cmd")
    if cmd:
        batch = _batch_file(command)
        return [cmd, "/c", batch], "cmd.exe", batch
    pwsh = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if pwsh:
        # PowerShell takes the command as a plain argument, so it needs no batch
        # file and there is nothing to clean up.
        return [pwsh, "-NoProfile", "-Command", command], "powershell", None
    raise RuntimeError(
        "no shell found: no POSIX shell, and neither cmd.exe nor "
        "powershell.exe is on PATH"
    )


#: Batch files live in the system temp directory rather than beside the project,
#: so a half-written command can never be picked up as a workspace file.
_TMP_DIR = Path(tempfile.gettempdir()) / "atlas-shell"


def _batch_file(command: str) -> str:
    """Write `command` to a one-shot `.cmd` and return its path."""
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(suffix=".cmd", dir=_TMP_DIR, text=True)
    with os.fdopen(handle, "w", encoding="utf-8", newline="\r\n") as fh:
        # `@echo off`: otherwise every line is echoed into the tool result and
        # a long command costs context tokens twice.
        fh.write("@echo off\r\n")
        fh.write(command)
    return name


def _discard(path: str | None) -> None:
    """Delete the one-shot batch file, ignoring any failure to."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    """End a command and everything it started. On Windows killing `sh.exe`
    leaves the `python.exe` it ran alive, so the whole tree goes (`taskkill /T`)."""
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        process.kill()


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def locate(path: str, workspace: Path, folders: list[Path]) -> Path | None:
    """Where a relative path belongs: the workspace first, then each allowed
    folder. An existing file wins; a new one (`Demo/Reports/x.xlsx`) goes
    where its folder already exists. None when the path is absolute, or names
    nothing anywhere (the caller then uses the workspace).

    The one rule for relative paths, as the filesystem MCP server already
    applies it: it lists `Demo/Invoices` from an allowed folder, so the
    reader script, the file and document tools and the `read` hint must find
    the same `Demo/Invoices/x.pdf`, not look in the chat's workspace only.
    """
    if not path or path.startswith("/") or os.path.isabs(path):
        return None
    roots = [Path(workspace), *map(Path, folders)]
    for root in roots:
        if (root / path).exists():
            return root / path
    if Path(path).parent != Path("."):
        for root in roots:
            if (root / path).parent.is_dir():
                return root / path
    return None


def default_environment(cwd: Path | None = None, skills: Path | None = None,
                        folders: list[Path] | None = None) -> NotASandboxLocalEnvironment:
    """The environment to use on this platform.

    Always the Windows subclass: where `sh` is found (as on POSIX) it runs
    commands through the stock implementation, so there is one code path.
    """
    return WindowsLocalEnvironment(cwd=cwd, skills=skills, folders=folders)


__all__ = ["WindowsLocalEnvironment", "default_environment", "drive_path", "model_path", "windows_path"]
"""A Windows execution environment for the harness `shell` tool.

**Why this file exists at all.** Strands' default "no sandbox" environment runs
every command as `sh -c <command>`. There is no `sh` on Windows, so every single
shell call failed with

    Error: ShellExecutionError - [WinError 2] The system cannot find the file specified

and every skill in this project is "run a script through `shell`", so documents
were dead while the scripts themselves worked perfectly when run outside the
agent.

`Sandbox` is an abstract base with six methods. Five (file reads and writes,
listing, removal) are OS-independent and inherited unchanged. Only the two
execution methods need a Windows implementation, so this subclasses the stock
local environment and overrides those two. Nothing in Strands is patched.

**Which shell it uses.** A POSIX shell, if one can be found -- Git Bash ships
with Git for Windows and is preferred, because then the stock implementation
works unmodified and the quoting in every `SKILL.md` behaves as written. Falling
back to `cmd.exe` costs three workarounds that exist only because of it: a
one-shot batch file (Windows re-quotes `argv`, breaking `python -c "..."`),
`_shared.unquote` (`cmd` leaves quotes attached to a path), and
`_shared.join_sql` (`cmd` splits a quoted SQL statement on its spaces). All three
are kept, because a script that tolerates mangled quoting cannot be broken by a
2B model, but none of them is on the happy path any more.

**What it is not.** A security boundary. Commands run on the host with the
backend's own privileges, exactly as the POSIX version does. The isolation
design.md relies on is "the agent works in `data/chats/<chat_id>/`", which is a
working-directory convention, not a sandbox. Do not treat this as one.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator

from strands.sandbox.base import ExecutionResult, StreamChunk
from strands.sandbox.not_a_sandbox_local_environment import (
    NotASandboxLocalEnvironment,
)

#: The interpreter used for `execute_code`. Atlas is a Python project and the
#: backend's own interpreter is the one with the venv's packages installed, so
#: `sys.executable` is correct rather than a bare `python`.
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

    def __init__(self) -> None:
        self.shell_dir = _find_posix_shell()

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
        try:
            if self.shell_dir is not None:
                async for chunk in super().execute_streaming(
                    command, timeout=timeout, cwd=cwd, env=_posix_env(env), **kwargs
                ):
                    yield chunk
                return

            async for chunk in self._cmd(command, timeout=timeout, cwd=cwd, env=env):
                yield chunk
        except Exception as exc:
            loop_name = type(asyncio.get_running_loop()).__name__
            # logger.exception("Shell execution failed under loop %s in %s", loop_name, cwd)
            yield ExecutionResult(
                stdout="",
                stderr=f"Shell execution failed [{type(exc).__name__}: {exc}] (loop={loop_name}, cwd={cwd or os.getcwd()})",
                exit_code=1,
            )
    
    async def _cmd(
        self,
        command: str,
        *,
        timeout: float | None,
        cwd: str | None,
        env: dict[str, str] | None,
    ) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        """The fallback: `cmd /c <one-shot batch file>`.

        A batch file rather than the command in `argv`. Passing it as an argument
        adds a re-quoting layer -- Python joins the argv list back into a command
        line, and if the command already contains quotes the result gets wrapped
        again, which trips `cmd`'s rule that a string beginning and ending in a
        quote has its *outer* pair stripped, leaving the inner ones as literal
        characters. The visible symptom was

            python -c "import sys"   ->   SyntaxError: unterminated string literal

        with the error pointing at `"import`, which reads as a broken script
        rather than a broken invocation. A batch file removes the layer: the
        command runs exactly as it would be if typed at a prompt.
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
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout or 120.0
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise
        finally:
            # Deleted whatever happened, including a timeout. A leaked .cmd per
            # tool call would otherwise accumulate for the life of the backend.
            _discard(batch)

        yield ExecutionResult(
            stdout=_decode(stdout),
            stderr=_decode(stderr),
            exit_code=process.returncode if process.returncode is not None else 1,
        )

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

        # `sys.executable` and `-c`, never a bare `python`: the bare name is not
        # on PATH inside a sandboxed shell, which is the same class of bug this
        # module exists to fix.
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_cmd_env(env),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout or 120.0
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        return ExecutionResult(
            stdout=_decode(stdout),
            stderr=_decode(stderr),
            exit_code=process.returncode if process.returncode is not None else 1,
        )

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


# ------------------------------------------------------- shell discovery --


def _find_posix_shell() -> Path | None:
    """Locate a POSIX shell and put it where `CreateProcess` will find it.

    Returns the directory to prepend to PATH, or None if there is no POSIX shell
    and the caller should fall back to `cmd.exe`.

    **PATH has to be changed process-wide, and that is not a preference.** Windows
    resolves an executable against the *calling* process's PATH; the environment
    passed to a child is consulted only after the image is found. So passing
    PATH through `env=` cannot make `sh` resolve -- measured, not assumed:
    `C:\\Program Files\\Git\\bin` was on `env["PATH"]` and every call still failed
    with `WinError 2`. `os.environ` is the only lever there is.

    The venv's `Scripts` directory goes first for a separate reason, and this is
    the fix for `No module named 'duckdb'`. Every skill script is a ready-made
    command the model runs as `python skills/.../read_xlsx.py`, and every one of
    them needs the venv's packages. Windows resolves `python` from PATH and the
    *system* Python sits there first, so a bare `python` loads a different
    interpreter than the one running the backend -- missing every dependency,
    which reads as "the script is broken" rather than "the wrong Python ran it".

    Two alternatives were tried and rejected: telling the model to use
    `sys.executable` in the system prompt (it wrote `python` anyway, and then ran
    `pip install duckdb` into user site-packages), and a `python.bat` shim, which
    shadows a deliberate `python` elsewhere. Putting the real interpreter first
    needs no cooperation from a 2B model: every command in every `SKILL.md` works
    verbatim as written.

    Derived from `sys.executable`, so it cannot drift from the interpreter
    actually running.
    """
    candidates: list[Path] = []
    found = shutil.which("sh") or shutil.which("bash")
    if found:
        candidates.append(Path(found).parent)
    candidates.extend(GIT_BIN_CANDIDATES)

    for directory in candidates:
        if not ((directory / "sh.exe").is_file() or (directory / "sh").is_file()):
            continue
        # **Both** directories, and the second one is the one that is easy to
        # miss. `bin` holds only the shells (`bash.exe`, `sh.exe`, `git.exe`);
        # the tools a shell command actually reaches for -- `tr`, `ls`, `grep`,
        # `sed`, `awk`, `find`, `wc` -- live in `usr/bin`. With only `bin` on
        # PATH the shell starts, then reports `command not found` for everything,
        # which reads as a broken Git install rather than a missing PATH entry.
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

    Derived from `sys.executable` so it cannot drift from the interpreter that is
    actually running. `VIRTUAL_ENV` is set too, so anything that shells out to
    `python -m ...` agrees with the rest.
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
    return merged


def _posix_env(env: dict[str, str] | None) -> dict[str, str]:
    """The environment a POSIX shell can actually accept.

    Drops the inherited Windows variables whose *names* are illegal POSIX
    identifiers -- `PROGRAMFILES(X86)` and `COMMONPROGRAMFILES(X86)` on a
    typical machine. Strands validates what it is asked to export and raises on
    them, so passing `os.environ` through unfiltered turns every shell call into
    a `ValueError`.

    Values are never dropped. A variable with a legal name but a Windows-shaped
    value is left alone, because the shell will pass it through untouched and
    some of them matter.

    **PATH is re-joined with `:` rather than `;`.** Measured, and it is the whole
    ballgame: handed a semicolon-separated PATH, bash found its own tools from
    `usr/bin` but silently could not find `python`, because `;` is not PATH's
    separator to it. With `:` it resolved both. MSYS translates the value back to
    Windows form for native children, so `.venv\\Scripts\\python.exe` still runs
    with the venv's packages -- verified by importing `duckdb` and `openpyxl`
    from inside the shell.
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
        # `@echo off` first, because a batch file echoes every line back by
        # default. That echo is pure noise in a tool result -- it goes straight
        # into the context window, so a long shell command would be paid for
        # twice, once to run and once to read back.
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


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def default_environment() -> NotASandboxLocalEnvironment:
    """The environment to use on this platform.

    Always the Windows subclass: on POSIX it defers to `super()` on every method,
    so behaviour is identical and there is one code path to test rather than two.
    """
    return WindowsLocalEnvironment()


__all__ = ["WindowsLocalEnvironment", "default_environment"]
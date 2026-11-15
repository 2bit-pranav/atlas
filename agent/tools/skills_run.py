"""Run a skill's script as a typed call, not a shell command.

Skill scripts ran through `shell`, and a shell command is a language: the
classifier recognised safe forms, and every hole in Phase 0 was a form it did
not (2026-11-12). `run_skill(skill, script, args)` runs one script of an
enabled skill: no shell, an argv list, the venv's Python, the chat workspace as
its folder, an environment without secrets (`inherited_env`). Nothing in `args`
is interpreted: `;`, `|`, `$(...)` are just characters.

The tool policy sees every path in `args` (`path_args`), placed exactly as this
tool places it: a file that exists is read, and an output may be created in its
folder (outputs never replace a file, `skills/_shared.py`); a name that does
not exist yet is created; the folder after an `--out...` option is written to.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from strands import tool

from agent.platform.windows_shell import _venv_first
from agent.tools.documents.tool import _failed

#: File types a script argument names, so "report.pdf:1-3" and "sales.xlsx:Mar" are paths.
SUFFIXES = {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".xls", ".csv", ".txt", ".md", ".pptx", ".json", ".html"}
_SPEC = re.compile(r"^(?P<path>.+?\.[A-Za-z0-9]{1,5})(?P<spec>:[^/\\:]*)?$")
_SCRIPT = re.compile(r"^[\w-]+\.py$")
TIMEOUT = 300
MAX_OUTPUT = 6000


def path_args(args: Iterable[str]) -> list[tuple[int, str, str, bool]]:
    """`(index, path, spec, written)` for each argument that names a file or folder.
    `written`: it follows an `--out...` option (a folder the script writes into)."""
    out, after_out = [], False
    for i, raw in enumerate(args):
        arg = str(raw)
        if arg.startswith("-"):
            after_out = arg.lstrip("-").lower().startswith("out") and "=" not in arg
            continue
        m = _SPEC.match(arg)
        if m and Path(m["path"]).suffix.lower() in SUFFIXES:
            out.append((i, m["path"], m["spec"] or "", after_out))
        elif "/" in arg or "\\" in arg or after_out:
            out.append((i, arg, "", after_out))
        after_out = False
    return out


def skill_effects(args: Iterable[str], place: Callable[[str], Path]) -> list[tuple[str, Path]]:
    """`(action, path)` for the grid: what running the script with `args` can do."""
    out: list[tuple[str, Path]] = []
    for _, raw, _, written in path_args(args):
        p = place(raw)
        if written:
            out.append(("create", p / "*"))
        elif p.exists():
            out += [("read", p), ("create", (p if p.is_dir() else p.parent) / "*")]
        else:
            out.append(("create", p))
    return out


def run(argv: list[str], cwd: Path, cancelled: Callable[[], bool], timeout: float = TIMEOUT) -> tuple[int | None, str]:
    """(exit code, output). None: stopped or timed out, the whole process tree ended."""
    proc = subprocess.Popen(argv, cwd=cwd, env=_venv_first({"ATLAS_WORKSPACE": str(cwd)}),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    end = time.monotonic() + timeout
    while True:
        try:
            raw, _ = proc.communicate(timeout=0.5)
            return proc.returncode, raw.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            if cancelled() or time.monotonic() > end:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
                proc.kill()
                proc.communicate()
                return None, "stopped" if cancelled() else f"took longer than {int(timeout)} s and was ended"


def skill_run_tools(skills_dir: Path, enabled: Callable[[], set[str]], workspace: Path,
                    resolve: Callable[[str], Path], cancelled: Callable[[], bool]) -> list[Any]:

    @tool(name="run_skill")
    def run_skill(skill: str, script: str, args: list[str] | None = None) -> Any:
        """Run one of a skill's scripts, as its SKILL.md says.

        Args:
            skill: The skill's name, e.g. "pdf".
            script: The script's file name, e.g. "merge_pdf.py".
            args: Its arguments, one string each, e.g. ["combined.pdf", "a.pdf", "b.pdf:1-3"].
        """
        args = [str(a) for a in (args or [])][:60]
        if skill not in enabled():
            return _failed(f"no enabled skill {skill!r}. Load a skill first with the skills tool.")
        folder = skills_dir / skill / "scripts"
        if not _SCRIPT.match(script) or not (folder / script).is_file():
            have = sorted(p.name for p in folder.glob("*.py")) if folder.is_dir() else []
            return _failed(f"{skill} has no script {script!r}. Its scripts: {', '.join(have) or 'none'}.")
        if any(len(a) > 1000 for a in args):
            return _failed("an argument is too long")
        # Paths as the policy checked them: placed in the workspace or the allowed folders.
        for i, raw, spec, _ in path_args(args):
            args[i] = str(resolve(raw)) + spec
        code, output = run([sys.executable, str(folder / script), *args], workspace, cancelled)
        output = output.strip()
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + f"\n[... {len(output) - MAX_OUTPUT:,} more characters not shown]"
        if code != 0:
            return _failed(f"{script} {'did not finish' if code is None else f'failed (exit {code})'}: {output or 'no output'}")
        return output or f"{script} finished."

    return [run_skill]


__all__ = ["path_args", "skill_effects", "skill_run_tools"]

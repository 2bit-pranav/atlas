"""What a skill needs installed, whether it is, and installing it on request.

Skills declare their needs in three ways in the wild, and all three are read:

- `requirements.txt` (in the skill folder or `scripts/`): Python packages.
- `package.json` in the skill folder: Node packages, installed into the
  skill's own `node_modules`.
- An install command written in SKILL.md, in a code block:
  `npm install -g agent-browser`, `pip install pypdf`. Many community skills
  only say it there.

Python packages go into the backend's own interpreter (`sys.executable -m
pip`), never wherever a bare `pip` points. Installing is only ever started by
the user, from the Skills page, so it needs no second approval.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_NPM = re.compile(r"^\s*(?:\$\s*)?(?:npm|pnpm)\s+(?:install|i|add)\s+(?P<flags>(?:-\S+\s+)*)(?P<pkgs>[^\n#;&|]+)", re.M)
_PIP = re.compile(r"^\s*(?:\$\s*)?(?:python3?\s+-m\s+)?(?:uv\s+)?pip3?\s+install\s+(?P<pkgs>[^\n#;&|]+)", re.M)
_SAFE = re.compile(r"^[A-Za-z0-9@][\w.@/+=<>~!-]*$")


def detect(folder: Path) -> list[dict[str, Any]]:
    """Every requirement a skill declares, de-duplicated, without status."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(manager: str, package: str, scope: str) -> None:
        package = package.strip().strip("\"'")
        if not package or package.startswith("-") or not _SAFE.match(package):
            return
        if (manager, package) not in seen:
            seen.add((manager, package))
            out.append({"manager": manager, "package": package, "scope": scope})

    for req in (folder / "requirements.txt", folder / "scripts" / "requirements.txt"):
        if req.is_file():
            for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip() and not line.lstrip().startswith(("#", "-")):
                    add("pip", line.split("#")[0], "env")
    package_json = folder / "package.json"
    if package_json.is_file():
        try:
            deps = json.loads(package_json.read_text(encoding="utf-8")).get("dependencies") or {}
        except (OSError, json.JSONDecodeError):
            deps = {}
        for name in deps:
            add("npm", name, "skill")
    manifest = folder / "SKILL.md"
    if manifest.is_file():
        text = manifest.read_text(encoding="utf-8", errors="replace")
        for block in _FENCE.findall(text):
            for m in _NPM.finditer(block):
                scope = "global" if re.search(r"(^|\s)(-g|--global)(\s|$)", m["flags"] or "") else "skill"
                for pkg in m["pkgs"].split():
                    add("npm", pkg, scope)
            for m in _PIP.finditer(block):
                for pkg in m["pkgs"].split():
                    add("pip", pkg, "env")
    return out


_npm_global: tuple[float, set[str]] | None = None


def _npm_globals() -> set[str]:
    """Globally installed npm packages, cached for a minute (npm is slow)."""
    global _npm_global
    if _npm_global and time.monotonic() - _npm_global[0] < 60:
        return _npm_global[1]
    npm = shutil.which("npm")
    names: set[str] = set()
    if npm:
        try:
            proc = subprocess.run([npm, "ls", "-g", "--depth=0", "--json"], capture_output=True,
                                  text=True, timeout=30)
            names = set((json.loads(proc.stdout or "{}").get("dependencies") or {}).keys())
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    _npm_global = (time.monotonic(), names)
    return names


def _bare(package: str) -> str:
    """`pypdf>=4` -> `pypdf`; `@scope/pkg@1.2` -> `@scope/pkg`."""
    if package.startswith("@"):
        return "@" + package[1:].split("@")[0]
    return re.split(r"[<>=!~@\[ ]", package, maxsplit=1)[0]


def with_status(folder: Path, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in requirements:
        name = _bare(r["package"])
        if r["manager"] == "pip":
            try:
                metadata.distribution(name)
                installed = True
            except metadata.PackageNotFoundError:
                installed = False
        elif r["scope"] == "global":
            installed = name in _npm_globals()
        else:
            installed = (folder / "node_modules" / name).is_dir()
        out.append({**r, "installed": installed})
    return out


def install(folder: Path, requirements: list[dict[str, Any]]) -> dict[str, Any]:
    """Install whatever is missing. Started by the user from the Skills page."""
    global _npm_global
    missing = [r for r in with_status(folder, requirements) if not r["installed"]]
    if not missing:
        return {"ok": True, "output": "Everything this skill needs is already installed."}
    logs, ok = [], True
    pip = [r["package"] for r in missing if r["manager"] == "pip"]
    if pip:
        ok &= _run([sys.executable, "-m", "pip", "install", *pip], None, logs)
    npm = shutil.which("npm")
    globals_ = [r["package"] for r in missing if r["manager"] == "npm" and r["scope"] == "global"]
    local = [r["package"] for r in missing if r["manager"] == "npm" and r["scope"] == "skill"]
    if (globals_ or local) and not npm:
        logs.append("npm is not installed, so the Node packages cannot be installed. Install Node.js first.")
        ok = False
    elif npm:
        if globals_:
            ok &= _run([npm, "install", "-g", *globals_], None, logs)
        if local:
            ok &= _run([npm, "install", *local], folder, logs)
        _npm_global = None
    return {"ok": ok, "output": "\n".join(logs)[-6000:]}


def _run(argv: list[str], cwd: Path | None, logs: list[str]) -> bool:
    logs.append("$ " + " ".join(argv[0:1] + argv[1:]))
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        logs.append(f"failed to start: {exc}")
        return False
    logs.append((proc.stdout + proc.stderr).strip()[-3000:])
    return proc.returncode == 0


__all__ = ["detect", "install", "with_status"]

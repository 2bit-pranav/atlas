"""Every offline check, in one command. CI runs exactly this.

    python tests/check.py            # all
    python tests/check.py py         # Python only (ruff, pyright, pytest)
    python tests/check.py ts         # TypeScript only (client, extension)

Exit code 0 only when everything passes. Pyright is a ratchet: the count of
errors may not rise above PYRIGHT_BASELINE (the count when it was introduced);
lower it here whenever errors are fixed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
#: pyright errors (basic mode) when the check was introduced, 2026-10-30.
PYRIGHT_BASELINE = 35


def _run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _tool(name: str) -> str:
    """A tool from this interpreter's environment, else from PATH."""
    here = Path(PYTHON).parent / (name + (".exe" if sys.platform == "win32" else ""))
    return str(here) if here.exists() else (shutil.which(name) or name)


def ruff() -> tuple[bool, str]:
    r = _run([_tool("ruff"), "check", "agent", "server", "skills", "tests"])
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if r.returncode else "clean"


def pyright() -> tuple[bool, str]:
    r = _run([_tool("pyright"), "agent", "server", "skills", "--pythonpath", PYTHON, "--level", "error",
              "--outputjson"])
    try:
        errors = json.loads(r.stdout)["summary"]["errorCount"]
    except (ValueError, KeyError):
        return False, (r.stdout + r.stderr).strip()[-300:]
    return errors <= PYRIGHT_BASELINE, f"{errors} errors (baseline {PYRIGHT_BASELINE})"


def pytest() -> tuple[bool, str]:
    r = _run([PYTHON, "-m", "pytest", "-q"])
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, lines[-1] if lines else "no output"


def _npx(folder: str, *args: str) -> tuple[bool, str]:
    npx = shutil.which("npx") or "npx"
    r = _run([npx, *args], cwd=ROOT / folder)
    out = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, "clean" if r.returncode == 0 else "\n".join(out[-15:])


CHECKS = {
    "py": [("ruff", ruff), ("pyright", pyright), ("pytest", pytest)],
    "ts": [("client tsc", lambda: _npx("client", "tsc", "-b", "--noEmit")),
           # Errors only: the remaining warnings are known (see oxlint's output).
           ("client oxlint", lambda: _npx("client", "oxlint")),
           ("client vitest", lambda: _npx("client", "vitest", "run")),
           ("extension tsc", lambda: _npx("extension", "tsc", "--noEmit")),
           ("extension vitest", lambda: _npx("extension", "vitest", "run"))],
}


def main() -> int:
    groups = sys.argv[1:] or list(CHECKS)
    failed = []
    for group in groups:
        for name, check in CHECKS[group]:
            t0 = time.time()
            ok, detail = check()
            print(f"{'PASS' if ok else 'FAIL'}  {name:16} {time.time() - t0:5.1f}s  {detail}", flush=True)
            if not ok:
                failed.append(name)
    print("\nall checks passed" if not failed else f"\nfailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

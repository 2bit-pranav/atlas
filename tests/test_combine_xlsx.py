"""skills/xlsx/scripts/combine_xlsx.py, run as the model runs it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "xlsx" / "scripts" / "combine_xlsx.py"


@pytest.mark.parametrize("stack", [[], ["--stack"]])
def test_combines_csvs(tmp_path, stack) -> None:
    """Side by side crashed: its `names` detail collided with created()'s parameter."""
    for name in ("jan", "feb"):
        (tmp_path / f"{name}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "out.xlsx", "jan.csv", "feb.csv", *stack],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "out.xlsx").is_file()

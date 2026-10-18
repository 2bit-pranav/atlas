"""`SkillManager` (design.md 1a and L5, tests T1a.2, T5.1-T5.3).

A skill is a folder with a `SKILL.md`: a name and a description the model sees
up front, and a body it loads only when it decides the skill applies. That
indirection is the point -- the catalogue is cheap, the body is not.

Skills are how documents get read (design.md L5). Each skill's `scripts/` holds
ready-made command-line tools, so the model runs `python skills/pdf/scripts/
read_pdf.py <path>` instead of writing library code. The model is 2B; asking it
to write correct `python-docx` code is a bad bet, and asking it to run a script
that already exists is not.

The one thing this manager insists on: an unknown name in `skills.enabled` is a
startup error. A typo there is otherwise indistinguishable from "the skill does
not work", and you would debug the model instead of the config.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agent.core.settings import Settings

logger = logging.getLogger(__name__)

#: A skill is a directory containing a SKILL.md.
MANIFEST = "SKILL.md"

#: Read from the front matter, or the first `# ` heading as a fallback. Both
#: are used in the wild, so both are accepted rather than one being required.
_FRONT_MATTER = re.compile(r"^---\s*$(.*?)^---\s*$", re.MULTILINE | re.DOTALL)
_NAME = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DESC = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


class SkillError(Exception):
    """A skill directory or `skills.enabled` entry is wrong."""


class SkillManager:
    """Discovers skill folders and filters them by `skills.enabled`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def skills_dir(self) -> Path:
        return Path(self.settings.skills.dir)

    # ------------------------------------------------------------ discover --

    def discover(self) -> list[dict[str, Any]]:
        """Every skill folder under the skills directory.

        Sorted by name so the catalogue the model sees is stable between turns;
        reordering it would change the prompt prefix and defeat the cache.
        """
        root = self.skills_dir()
        if not root.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for child in sorted(root.iterdir()):
            manifest = child / MANIFEST
            if not child.is_dir() or not manifest.is_file():
                continue
            try:
                found.append(self._read(manifest, child))
            except SkillError as exc:
                raise SkillError(f"{manifest}: {exc}") from exc
        return sorted(found, key=lambda s: s["name"])

    def _read(self, manifest: Path, folder: Path) -> dict[str, Any]:
        text = manifest.read_text(encoding="utf-8")
        name = desc = None

        if (fm := _FRONT_MATTER.search(text)) is not None:
            block = fm.group(1)
            if (m := _NAME.search(block)) is not None:
                name = m.group(1).strip().strip("\"'")
            if (m := _DESC.search(block)) is not None:
                desc = m.group(1).strip().strip("\"'")

        if not name or not desc:
            # Fall back to the first heading and the line under it.
            for line in text.splitlines():
                if not name and line.startswith("# "):
                    name = line[2:].strip()
                if not desc and line.strip() and not line.startswith(("#", "-", "|")):
                    desc = line.strip()
                if name and desc:
                    break

        if not name or not desc:
            raise SkillError(
                "needs a name and a description, in front matter "
                "(name: ... / description: ...) or as a heading and the line below it"
            )
        return {
            "name": name,
            "description": desc,
            "folder": folder.name,
            "path": str(folder),
            "scripts": sorted(
                p.name for p in (folder / "scripts").glob("*") if p.is_file()
            ) if (folder / "scripts").is_dir() else [],
        }

    # -------------------------------------------------------------- filter --

    def enabled(self) -> list[dict[str, Any]]:
        """The skills the harness should offer, validated.

        An empty `skills.enabled` means "all". A non-empty one that names
        something absent is an error, not a silent skip.
        """
        available = self.discover()
        wanted = [n.strip() for n in self.settings.skills.enabled if n.strip()]
        if not wanted:
            return available

        by_name = {s["name"]: s for s in available}
        by_folder = {s["folder"]: s for s in available}
        unknown = [
            n for n in wanted if n not in by_name and n not in by_folder
        ]
        if unknown:
            raise SkillError(
                f"skills.enabled names {unknown}, which do not exist. "
                f"Available: {sorted(by_name) or 'none found'}"
            )
        chosen = [by_name.get(n) or by_folder[n] for n in wanted]
        return sorted(chosen, key=lambda s: s["name"])

    def harness_skills(self) -> Any:
        """The `skills=` argument for `create_harness`.

        The harness accepts a bool, a `SkillSources`, or an `AgentSkills`. A
        single skills directory is the simplest thing that satisfies
        `skills.enabled` for now, because filtering happens inside the folder
        list below. T1a.2 asks whether a list of individual folders works; if
        it does, this returns that instead and `enabled()` is only validation.
        """
        if not self.enabled():
            return False
        directory = self.skills_dir()
        if not directory.is_dir():
            return False
        return str(directory)

    def catalogue(self) -> list[dict[str, Any]]:
        """For `GET /skills` and the CLI: what the model will see."""
        return self.enabled()


__all__ = ["MANIFEST", "SkillError", "SkillManager"]
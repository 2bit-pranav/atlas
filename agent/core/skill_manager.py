"""`SkillManager`: which skills exist, and which the agent gets.

A skill is a folder with a `SKILL.md`: a name and a description the model sees
up front, and a body it loads only when it decides the skill applies. That
indirection is the point -- the catalogue is cheap, the body is not.

Skills are how documents get read. The harness's own `read` tool returns a pdf,
docx or xlsx as a `document` block, which the llama.cpp adapter cannot send to
the model, and `write`/`edit` are text-only. So each skill's `scripts/` holds a
ready-made command-line tool and the model runs it through `shell`. The model
is 2B; asking it to write correct `python-docx` code is a bad bet, and asking
it to run a script that already exists is not.

Every discovered skill is on unless its folder is listed in
`skills.disabled`, so a freshly installed skill works with no second step. A
skill whose `SKILL.md` cannot be read is reported with its error rather than
taking the whole catalogue down with it -- community skills arrive in many
shapes, and one bad one must not disable the other twenty.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from agent.core import paths
from agent.core import skill_requirements as requirements
from agent.core.settings import Settings

logger = logging.getLogger(__name__)

#: A skill is a directory containing a SKILL.md.
MANIFEST = "SKILL.md"

#: Read from the front matter, or the first `# ` heading as a fallback. Both
#: are used in the wild, so both are accepted rather than one being required.
_FRONT_MATTER = re.compile(r"\A\s*---\s*$(.*?)^---\s*$", re.MULTILINE | re.DOTALL)
_NAME = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DESC = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


class SkillError(Exception):
    """A skill directory is unusable, or an install or delete was refused."""


class SkillManager:
    """Discovers skill folders and filters them by `skills.disabled`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def skills_dir(self) -> Path:
        return paths.skills_dir(self.settings)

    # ------------------------------------------------------------ discover --

    def discover(self) -> list[dict[str, Any]]:
        """Every skill folder under the skills directory, readable or not.

        Sorted by name so the catalogue the model sees is stable between turns;
        reordering it would change the prompt prefix and defeat the cache.
        """
        root = self.skills_dir()
        if not root.is_dir():
            return []
        # Here, not at the top: the installer imports this module.
        from agent.core.skill_installer import body_tokens, origin_of

        disabled = set(self.settings.skills.disabled)
        found: list[dict[str, Any]] = []
        for child in root.iterdir():
            manifest = child / MANIFEST
            if not child.is_dir() or not manifest.is_file():
                continue
            try:
                entry = read_manifest(manifest)
                entry["error"] = None
            except (SkillError, OSError, UnicodeDecodeError) as exc:
                entry = {"name": child.name, "description": "", "error": str(exc)}
            entry.update(
                folder=child.name,
                path=str(child),
                enabled=child.name not in disabled and entry["error"] is None,
                scripts=_listing(child / "scripts"),
                requirements=requirements.with_status(child, requirements.detect(child)),
                bytes=sum(p.stat().st_size for p in child.rglob("*") if p.is_file()),
                tokens=body_tokens(child),
                origin=origin_of(child),
                bundled=origin_of(child) is None,
            )
            found.append(entry)
        return sorted(found, key=lambda s: s["name"].lower())

    # -------------------------------------------------------------- filter --

    def enabled(self) -> list[dict[str, Any]]:
        return [s for s in self.discover() if s["enabled"]]

    def harness_skills(self) -> Any:
        """The `skills=` argument for `create_harness`: one path per enabled skill.

        The SDK's `AgentSkills` takes a list of individual skill directories, so
        filtering is a matter of passing fewer of them. `False` when none are on,
        which keeps the `skills` tool out of the request entirely.
        """
        chosen = [s["path"] for s in self.enabled()]
        return chosen or False

    def catalogue(self) -> list[dict[str, Any]]:
        """For `GET /skills`: every skill, with its switch and any error."""
        return self.discover()


#: File type -> (skill folder, reader script). The bundled readers.
READERS: dict[str, tuple[str, str]] = {
    ".pdf": ("pdf", "read_pdf.py"),
    ".docx": ("docx", "read_docx.py"),
    ".xlsx": ("xlsx", "read_xlsx.py"),
    ".xlsm": ("xlsx", "read_xlsx.py"),
}


def reader_command(settings: Settings, path: str, shown: str) -> str | None:
    """The exact shell command that reads `path`, if an enabled skill can.

    Named in the attachment list and in the `read` guard, so the model runs
    the right script first time instead of trying `read`, getting nothing
    useful back, and loading the skill to find out what to run.
    """
    reader = READERS.get(Path(path).suffix.lower())
    if reader is None:
        return None
    folder, script = reader
    if folder in settings.skills.disabled:
        return None
    script_path = paths.skills_dir(settings) / folder / "scripts" / script
    if not script_path.is_file():
        return None
    extra = " --pages all" if folder == "pdf" else ""
    return f'python "$ATLAS_SKILLS/{folder}/scripts/{script}" "{shown}"{extra}'


def read_manifest(manifest: Path) -> dict[str, Any]:
    """Name and description from a SKILL.md, or `SkillError`."""
    text = manifest.read_text(encoding="utf-8")
    name = desc = None

    if (fm := _FRONT_MATTER.search(text)) is not None:
        # Real YAML: community skills use folded (`>`) and literal (`|`)
        # descriptions, which a line regex reads as the single character ">".
        try:
            meta = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        if isinstance(meta, dict):
            name = str(meta.get("name") or "").strip() or None
            desc = " ".join(str(meta.get("description") or "").split()) or None
        block = fm.group(1)
        if not name and (m := _NAME.search(block)) is not None:
            name = m.group(1).strip().strip("\"'")
        if not desc and (m := _DESC.search(block)) is not None:
            desc = m.group(1).strip().strip("\"'")

    if not name or not desc:
        # Fall back to the first heading and the line under it.
        for line in text.splitlines():
            if not name and line.startswith("# "):
                name = line[2:].strip()
            if not desc and line.strip() and not line.startswith(("#", "-", "|", "---")):
                desc = line.strip()
            if name and desc:
                break

    if not name or not desc:
        raise SkillError(
            "needs a name and a description, in front matter "
            "(name: ... / description: ...) or as a heading and the line below it"
        )
    return {"name": name, "description": desc}


def _listing(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file())


__all__ = ["MANIFEST", "READERS", "SkillError", "SkillManager", "read_manifest", "reader_command"]

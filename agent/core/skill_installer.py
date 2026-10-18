"""Installing and removing skills: from a skills.sh command, a GitHub URL, or a zip.

skills.sh lists community skills and shows an install command per skill:

    npx skills add https://github.com/anthropics/skills --skill pdf

Running that command would need Node, ask interactive questions, and install
into a coding agent's own folder. Atlas reads it instead: the command names a
GitHub repository and optionally a skill, which is all that is needed to fetch
the folder directly. No API key, no npx, nothing executed.

Every installed skill gets a `.atlas-source.json` recording where it came from.
Skills without one shipped with Atlas; those can be switched off but not
deleted from the UI, because deleting them would show up as a source change.

Community skills are written for large coding agents. Two things are reported
so the user can judge fit for a 2B model before relying on one: how many tokens
the SKILL.md body costs when loaded, and the Python packages it declares. The
packages are never installed by the model; `install_requirements` exists for
the user to run from the UI after reading the list.
"""

from __future__ import annotations

import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.skill_manager import MANIFEST, SkillError, read_manifest

SOURCE_FILE = ".atlas-source.json"
_GITHUB = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/]+)(?:/(?P<path>.+?))?)?/?$"
)
_SHORT = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$")
_SKILL_NAME = re.compile(r"^[\w.-]+$")
#: A downloaded repository larger than this is refused rather than unpacked.
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024


@dataclass
class Source:
    owner: str
    repo: str
    ref: str = "HEAD"
    path: str = ""
    skills: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"github.com/{self.owner}/{self.repo}" + (f"/{self.path}" if self.path else "")


def parse_source(text: str) -> Source:
    """A skills.sh command, a GitHub URL, or `owner/repo` -> where to fetch from."""
    text = text.strip().strip("`").strip()
    if text.startswith("$"):
        text = text[1:].strip()
    try:
        words = shlex.split(text, posix=True)
    except ValueError as exc:
        raise SkillError(f"could not read that command: {exc}") from exc
    if not words:
        raise SkillError("paste a skills.sh install command or a GitHub URL")

    # `npx skills add <src> [--skill name]...`, `npx -y skills add ...`, or a bare source.
    if words[0] in ("npx", "pnpx", "bunx"):
        words = [w for w in words[1:] if not w.startswith("-y") and w != "--yes"]
        if len(words) < 3 or words[0].split("@")[0] != "skills" or words[1] not in ("add", "install", "i"):
            raise SkillError("expected `npx skills add <owner/repo or GitHub URL> [--skill name]`")
        words = words[2:]

    target, skills, rest = None, [], iter(words)
    for word in rest:
        if word in ("--skill", "-s"):
            name = next(rest, "")
            if not _SKILL_NAME.match(name):
                raise SkillError(f"not a skill name: {name!r}")
            skills.append(name)
        elif word.startswith("--skill="):
            skills.append(word.split("=", 1)[1])
        elif word.startswith("-"):
            continue  # flags meant for the npx installer (agent selection, -g, ...)
        elif target is None:
            target = word
    if target is None:
        raise SkillError("no repository given")

    if (m := _GITHUB.match(target)) is not None:
        return Source(m["owner"], m["repo"], m["ref"] or "HEAD", (m["path"] or "").strip("/"),
                      tuple(skills))
    if (m := _SHORT.match(target)) is not None:
        return Source(m["owner"], m["repo"], skills=tuple(skills))
    raise SkillError(f"only GitHub sources are supported, not {target!r}")


# --------------------------------------------------------------- fetching --


def _download(source: Source) -> bytes:
    import httpx

    url = f"https://codeload.github.com/{source.owner}/{source.repo}/tar.gz/{source.ref}"
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
        if response.status_code == 404:
            raise SkillError(f"{source.label} was not found (or is private)")
        response.raise_for_status()
        buf = io.BytesIO()
        for chunk in response.iter_bytes():
            buf.write(chunk)
            if buf.tell() > MAX_ARCHIVE_BYTES:
                raise SkillError(f"{source.label} is larger than {MAX_ARCHIVE_BYTES >> 20} MB")
    return buf.getvalue()


def _safe_extract_tar(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")  # refuses absolute paths, links out, devices


def _safe_extract_zip(data: bytes, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (dest / member.filename).resolve()
            if root != target and root not in target.parents:
                raise SkillError(f"the zip contains an unsafe path: {member.filename}")
        archive.extractall(dest)


def _candidates(root: Path) -> list[dict[str, Any]]:
    """Every folder under `root` with a readable SKILL.md."""
    found = []
    for manifest in sorted(root.rglob(MANIFEST)):
        if any(part.startswith(".") for part in manifest.relative_to(root).parts[:-1]):
            continue
        try:
            meta = read_manifest(manifest)
        except (SkillError, UnicodeDecodeError):
            continue
        found.append({**meta, "dir": manifest.parent, "folder": manifest.parent.name})
    return found


# ------------------------------------------------------------- installing --


def preview_or_install(skills_dir: Path, text: str, *, choose: list[str] | None = None,
                       replace: bool = False) -> dict[str, Any]:
    """Install from a command or URL.

    When the source holds several skills and none was named, nothing is
    installed and the choices are returned, so the UI can ask which ones.
    """
    source = parse_source(text)
    wanted = list(choose or source.skills)
    with tempfile.TemporaryDirectory(prefix="atlas-skill-") as tmp:
        tmpdir = Path(tmp)
        _safe_extract_tar(_download(source), tmpdir)
        tops = [p for p in tmpdir.iterdir() if p.is_dir()]
        root = tops[0] if len(tops) == 1 else tmpdir
        if source.path:
            root = root / source.path
            if not root.is_dir():
                raise SkillError(f"{source.label} has no folder {source.path!r}")
        found = _candidates(root)
        if not found:
            raise SkillError(f"no SKILL.md found in {source.label}")
        if not wanted:
            if len(found) > 1:
                return {"installed": [], "choices": [_choice(c) for c in found]}
            wanted = [found[0]["folder"]]
        picked = _pick(found, wanted, source.label)
        installed = [_install_dir(skills_dir, c, {"type": "github", "source": source.label,
                                                  "command": text.strip(), "ref": source.ref},
                                  replace=replace) for c in picked]
    return {"installed": installed, "choices": []}


def install_zip(skills_dir: Path, data: bytes, filename: str, *, replace: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="atlas-skill-") as tmp:
        tmpdir = Path(tmp)
        try:
            _safe_extract_zip(data, tmpdir)
        except zipfile.BadZipFile as exc:
            raise SkillError(f"{filename} is not a zip file") from exc
        found = _candidates(tmpdir)
        if not found:
            raise SkillError(f"no SKILL.md found in {filename}")
        installed = [_install_dir(skills_dir, c, {"type": "upload", "source": filename},
                                  replace=replace) for c in found]
    return {"installed": installed, "choices": []}


def _pick(found: list[dict[str, Any]], wanted: list[str], label: str) -> list[dict[str, Any]]:
    by_key = {}
    for c in found:
        by_key.setdefault(c["folder"], c)
        by_key.setdefault(c["name"], c)
    missing = [w for w in wanted if w not in by_key]
    if missing:
        raise SkillError(f"{label} has no skill named {missing}. "
                         f"It has: {sorted({c['folder'] for c in found})}")
    return list({id(by_key[w]): by_key[w] for w in wanted}.values())


def _choice(c: dict[str, Any]) -> dict[str, Any]:
    return {"name": c["name"], "folder": c["folder"], "description": c["description"]}


def _install_dir(skills_dir: Path, candidate: dict[str, Any], origin: dict[str, Any],
                 *, replace: bool) -> dict[str, Any]:
    folder = candidate["folder"]
    if not _SKILL_NAME.match(folder):
        raise SkillError(f"unsafe skill folder name {folder!r}")
    target = skills_dir / folder
    if target.exists():
        if not (target / SOURCE_FILE).is_file():
            raise SkillError(f"{folder!r} is a bundled skill and cannot be replaced")
        if not replace:
            raise SkillError(f"{folder!r} is already installed. Delete it first, or reinstall.")
        shutil.rmtree(target)
    skills_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(candidate["dir"], target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    (target / SOURCE_FILE).write_text(
        json.dumps({**origin, "installed_at": int(time.time() * 1000)}, indent=2), encoding="utf-8")
    return {"name": candidate["name"], "folder": folder}


# ------------------------------------------------------------- removing --


def delete_skill(skills_dir: Path, folder: str) -> None:
    if not _SKILL_NAME.match(folder):
        raise SkillError(f"not a skill folder: {folder!r}")
    target = skills_dir / folder
    if not target.is_dir():
        raise SkillError(f"no skill {folder!r}")
    if not (target / SOURCE_FILE).is_file():
        raise SkillError(f"{folder!r} shipped with Atlas: switch it off instead of deleting it")
    shutil.rmtree(target)


def origin_of(skill_dir: Path) -> dict[str, Any] | None:
    path = skill_dir / SOURCE_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"type": "unknown"}


def body_tokens(skill_dir: Path) -> int:
    """What loading the skill costs the context window, roughly."""
    try:
        return len((skill_dir / MANIFEST).read_text(encoding="utf-8", errors="replace")) // 4
    except OSError:
        return 0


def install_requirements(requirements: list[str]) -> dict[str, Any]:
    """`pip install` into the backend's own interpreter. Only ever user-initiated."""
    if not requirements:
        return {"ok": True, "output": "nothing to install"}
    for req in requirements:
        if req.startswith("-") or any(c in req for c in ";|&`$"):
            raise SkillError(f"refusing an unusual requirement line: {req!r}")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", *requirements],
                          capture_output=True, text=True, timeout=600)
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr)[-6000:]}


__all__ = [
    "SOURCE_FILE",
    "Source",
    "body_tokens",
    "delete_skill",
    "install_requirements",
    "install_zip",
    "origin_of",
    "parse_source",
    "preview_or_install",
]

"""Skills: installing one never reaches outside its download, and an archive
cannot unpack to more than the caps (installer.py); what a skill needs
installed (requirements.py)."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from agent.integrations.skills import installer
from agent.integrations.skills import requirements as skill_requirements
from agent.integrations.skills.catalog import SkillError
from agent.integrations.skills.installer import install_zip, preview_or_install

SKILL = b"---\nname: demo\ndescription: a demo skill\n---\nDo the demo.\n"


def _tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def repo(monkeypatch):
    archive = _tar({"repo-main/skills/demo/SKILL.md": SKILL})
    monkeypatch.setattr(installer, "_download", lambda source: archive)


def test_a_folder_inside_the_repository_installs(tmp_path, repo) -> None:
    out = preview_or_install(tmp_path / "skills", "https://github.com/o/repo/tree/main/skills")
    assert [s["folder"] for s in out["installed"]] == ["demo"]


@pytest.mark.parametrize("url", [
    "https://github.com/o/repo/tree/main/../../..",
    "https://github.com/o/repo/tree/main/skills/../../../outside",
])
def test_a_path_outside_the_repository_is_refused(tmp_path, repo, url) -> None:
    """`..` in the URL's folder pointed the installer outside its download."""
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "SKILL.md").write_bytes(SKILL)
    with pytest.raises(SkillError, match="outside the repository"):
        preview_or_install(tmp_path / "skills", url)
    assert not (tmp_path / "skills").exists()


def test_a_tar_that_unpacks_too_large_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "MAX_EXTRACTED_BYTES", 1000)
    archive = _tar({"repo-main/SKILL.md": SKILL, "repo-main/big.bin": b"\0" * 5000})
    monkeypatch.setattr(installer, "_download", lambda source: archive)
    with pytest.raises(SkillError, match="unpacks"):
        preview_or_install(tmp_path / "skills", "o/repo")


def test_a_zip_bomb_is_refused_before_extracting(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "MAX_EXTRACTED_BYTES", 1000)
    data = _zip({"demo/SKILL.md": SKILL, "demo/big.bin": b"\0" * 50_000})    # compresses to almost nothing
    assert len(data) < 1000
    with pytest.raises(SkillError, match="unpacks"):
        install_zip(tmp_path / "skills", data, "bomb.zip")
    assert not (tmp_path / "skills").exists()


def test_too_many_files_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(installer, "MAX_FILES", 5)
    data = _zip({"demo/SKILL.md": SKILL, **{f"demo/f{i}.txt": b"x" for i in range(10)}})
    with pytest.raises(SkillError, match="files"):
        install_zip(tmp_path / "skills", data, "many.zip")


def test_a_zip_path_outside_is_still_refused(tmp_path) -> None:
    data = _zip({"../evil/SKILL.md": SKILL})
    with pytest.raises(SkillError, match="unsafe path"):
        install_zip(tmp_path / "skills", data, "evil.zip")


def test_requirements_detected_from_all_three_sources(tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("pypdf>=4  # pdfs\n# comment\n-r other.txt\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "^1"}}')
    (tmp_path / "SKILL.md").write_text(
        "Install:\n```bash\nnpm install -g agent-browser\npip install pypdf rich\n```\n"
        "Not in a fence: pip install ignored\n")
    found = {(r["manager"], r["package"], r["scope"]) for r in skill_requirements.detect(tmp_path)}
    assert found == {("pip", "pypdf>=4", "env"), ("npm", "left-pad", "skill"),
                     ("npm", "agent-browser", "global"), ("pip", "pypdf", "env"), ("pip", "rich", "env")}


def test_requirement_status_for_pip() -> None:
    status = skill_requirements.with_status(Path("."), [
        {"manager": "pip", "package": "pytest>=1", "scope": "env"},
        {"manager": "pip", "package": "surely-not-installed-xyz", "scope": "env"}])
    assert [r["installed"] for r in status] == [True, False]

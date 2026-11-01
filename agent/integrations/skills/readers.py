"""The exact command that reads a document type, for the model and the read hint."""

from __future__ import annotations

from pathlib import Path

from agent.config import paths
from agent.config.settings import Settings

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
    # No `--pages all`: the reader reads a short PDF whole by itself, and on a
    # 67-page scanned one "all" meant minutes of OCR. Its header gives the
    # page count, so the model can search or read a range next.
    return f'python "$ATLAS_SKILLS/{folder}/scripts/{script}" "{shown}"'


__all__ = ["READERS", "reader_command"]

"""read_text / read_image (agent/tools/reading.py), which replace the harness `read`."""

from __future__ import annotations

from pathlib import Path

from agent.tools.reading import MAX_CHARS, read_tools


def _tools(ws: Path, vision: bool = True):
    reader = lambda p: f'python read_pdf.py "{p}"' if p.endswith(".pdf") else None  # noqa: E731
    text, image = read_tools(lambda p: ws / p, lambda p: p.name, reader, vision)
    return text, image


def _text(result) -> str:
    return result if isinstance(result, str) else result["content"][0]["text"]


def test_a_long_file_is_capped_and_says_how_to_go_on(tmp_path) -> None:
    """The harness `read` returned a 3,000-line log whole and overflowed the context."""
    (tmp_path / "server.log").write_text("\n".join(f"line {i} " + "x" * 50 for i in range(3000)))
    text, _ = _tools(tmp_path)
    out = text(path="server.log")
    assert len(out) < MAX_CHARS + 400
    assert out.startswith("server.log: lines 1-")
    shown = int(out.split("lines 1-", 1)[1].split(" ", 1)[0])
    assert f"start_line={shown + 1}" in out
    nxt = text(path="server.log", start_line=shown + 1, end_line=shown + 2)
    assert f"lines {shown + 1}-{shown + 2} of 3000" in nxt


def test_search_matches_words_not_the_phrase(tmp_path) -> None:
    lines = [f"INFO request {i}" for i in range(500)]
    lines[417] = "ERROR worker-3 disk quota exceeded (code E-7731)"
    (tmp_path / "a.log").write_text("\n".join(lines))
    text, _ = _tools(tmp_path)
    out = text(path="a.log", search="worker-3 quota error code")
    assert "418\tERROR worker-3" in out and "1 line" in out
    assert "No line" in text(path="a.log", search="nothing-here")


def test_long_lines_are_cut(tmp_path) -> None:
    (tmp_path / "min.js").write_text("a" * 50_000)
    text, _ = _tools(tmp_path)
    out = text(path="min.js")
    assert "line cut, 50,000 chars" in out and len(out) < 1000


def test_wrong_file_types_name_the_right_tool(tmp_path) -> None:
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02")
    text, image = _tools(tmp_path)
    for result, needle in ((text(path="report.pdf"), 'python read_pdf.py "report.pdf"'),
                           (text(path="pic.png"), "read_image"),
                           (text(path="blob.bin"), "binary"),
                           (text(path="gone.txt"), "no file gone.txt"),
                           (image(path="report.pdf"), "read_text")):
        assert result["status"] == "error" and needle in _text(result), needle


def test_read_image_returns_the_image(tmp_path) -> None:
    (tmp_path / "pic.jpg").write_bytes(b"\xff\xd8jpeg")
    _, image = _tools(tmp_path)
    block = image(path="pic.jpg")["content"][0]["image"]
    assert block["format"] == "jpeg" and block["source"]["bytes"] == b"\xff\xd8jpeg"
    _, blind = _tools(tmp_path, vision=False)
    assert blind(path="pic.jpg")["status"] == "error"


def test_a_long_text_attachment_is_announced_with_its_search_form(tmp_path) -> None:
    """Told only to read it, the model read the first lines and said the log had no errors."""
    from server.services.prompt import _agent_text

    (tmp_path / "short.txt").write_text("a\n" * 10)
    (tmp_path / "long.log").write_text("a\n" * 400)
    files = [{"path": str(tmp_path / n), "name": n, "size": 1} for n in ("short.txt", "long.log", "pic.png")]
    text = _agent_text("q", files, reader=lambda p, s: None, workspace=tmp_path)
    assert 'short.txt at' in text and 'read_text(path="short.txt")' in text
    assert 'it has 400 lines, so to find something use read_text(path="long.log", search="words")' in text
    assert "pic.png" in text and 'read_text(path="pic.png")' not in text   # images go to the model as they are

"""The extension's file basket (agent/extension/basket.py, form_fill.suggest, the basket routes):
files found for a form's upload fields, handed out by short-lived id, checked again when served."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from helpers import settings_file

from agent.config.settings import load_settings
from agent.extension import basket as basket_mod
from agent.extension import form_fill
from agent.extension.basket import Basket, candidates, refusal
from server.app import create_app


@pytest.fixture
def home(tmp_path):
    docs = tmp_path / "Docs"
    (docs / "Career").mkdir(parents=True)
    (docs / "Photos").mkdir()
    (docs / "Career" / "Resume_2026.pdf").write_bytes(b"%PDF-1.4 resume")
    (docs / "Career" / "Resume_2019.docx").write_bytes(b"PK old resume")
    (docs / "Photos" / "passport.jpg").write_bytes(b"\xff\xd8 photo")
    # Atlas's own data inside an allowed folder: never offered.
    (docs / "atlas-data").mkdir()
    (docs / "atlas-data" / "resume_backup.pdf").write_bytes(b"%PDF-1.4 not yours to hand out")
    path = settings_file(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.setdefault("access", {})["folders"] = [str(docs)]
    raw["paths"]["data_dir"] = str(docs / "atlas-data")
    path.write_text(json.dumps(raw), encoding="utf-8")
    return tmp_path, path


def test_an_upload_field_finds_its_file_by_label_and_type(home) -> None:
    _, path = home
    settings = load_settings(path)
    assert [p.name for p in candidates(settings, "Upload your resume", ".pdf")] == ["Resume_2026.pdf"]
    assert [p.name for p in candidates(settings, "Passport size photo", "image/*")] == ["passport.jpg"]
    assert "Resume_2019.docx" in [p.name for p in candidates(settings, "Upload your resume")]
    assert "resume_backup.pdf" not in [p.name for p in candidates(settings, "resume backup")]   # Atlas's own data


def test_a_file_is_checked_again_when_it_is_handed_out(home) -> None:
    tmp, path = home
    settings = load_settings(path)
    resume = tmp / "Docs" / "Career" / "Resume_2026.pdf"
    assert refusal(settings, resume) is None
    assert refusal(settings, tmp / "Docs" / "atlas-data" / "resume_backup.pdf") == "Atlas's own files are never handed out"
    outside = tmp / "elsewhere.pdf"
    outside.write_bytes(b"x")
    assert refusal(settings, outside) == "the file is not in your allowed folders"
    resume.unlink()
    assert refusal(settings, resume) == "the file is no longer there"


def test_fill_offers_files_as_cards_never_as_typed_values(home, monkeypatch) -> None:
    _, path = home
    settings = load_settings(path)
    sent: dict = {}

    class Reply:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            schema = sent["body"]["response_format"]["json_schema"]["schema"]["properties"]
            pick = schema["u1"]["items"]["enum"][0]
            return {"choices": [{"message": {"content": json.dumps({"u1": [pick]})}}]}

    def post(url, json, headers, timeout):
        sent["body"] = json
        return Reply()

    monkeypatch.setattr(form_fill.httpx, "post", post)
    basket = Basket()
    out = form_fill.suggest(settings, [{"id": "u1", "label": "Upload your resume", "type": "file", "accept": ".pdf"}],
                            "Internship", basket)
    assert "Resume_2026.pdf (Docs/Career)" in sent["body"]["messages"][1]["content"]
    assert out["values"] == {} and out["missing"] == []
    [card] = out["files"]
    assert card["name"] == "Resume_2026.pdf" and card["folder"] == "Docs/Career" and card["available"]
    assert basket.get(card["id"]).path.name == "Resume_2026.pdf"


def test_the_extension_gets_only_ids_fill_handed_out(home) -> None:
    tmp, path = home
    app = create_app(path)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    token = (tmp / "Docs" / "atlas-data" / "pairing-token").read_text(encoding="utf-8").strip()
    ext = {"Origin": "chrome-extension://abc", "Authorization": f"Bearer {token}"}
    atlas = app.state.atlas
    try:
        key = atlas.basket.offer(tmp / "Docs" / "Career" / "Resume_2026.pdf", "Resume")
        got = client.get(f"/api/extension/basket/{key}", headers=ext)
        assert got.status_code == 200 and got.content == b"%PDF-1.4 resume"
        assert client.get("/api/extension/basket/b-madeupid123456", headers=ext).status_code == 404
        assert client.get(f"/api/extension/basket?ids={key}", headers=ext).json()[0]["available"] is True
        # Moved since Fill found it: refused, and the card says why.
        (tmp / "Docs" / "Career" / "Resume_2026.pdf").rename(tmp / "moved.pdf")
        assert client.get(f"/api/extension/basket/{key}", headers=ext).status_code == 409
        assert client.get(f"/api/extension/basket?ids={key}", headers=ext).json()[0]["problem"] == "the file is no longer there"
        # Without the extension's token, a web page gets nothing.
        assert client.get(f"/api/extension/basket/{key}", headers={"Origin": "https://evil.example"}).status_code == 403
    finally:
        atlas.close()


def test_a_basket_entry_expires(home, monkeypatch) -> None:
    tmp, _ = home
    basket = Basket()
    key = basket.offer(tmp / "Docs" / "Photos" / "passport.jpg", "Photo")
    monkeypatch.setattr(basket_mod.time, "time", lambda: 10**12)
    assert basket.get(key) is None


def test_files_are_offered_even_when_the_model_picks_none(home, monkeypatch) -> None:
    """Told to "never invent", the model picked no file for "Resume" though Resume.pdf was found."""
    _, path = home
    settings = load_settings(path)

    class Reply:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps({"u1": []})}}]}

    monkeypatch.setattr(form_fill.httpx, "post", lambda *a, **k: Reply())
    out = form_fill.suggest(settings, [{"id": "u1", "label": "Resume", "type": "file"}], "", Basket())
    assert {c["name"] for c in out["files"]} >= {"Resume_2026.pdf", "Resume_2019.docx"}
    assert out["missing"] == []


"""What a model can do, from its GGUF headers (agent/model/gguf.py)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from agent.model.gguf import GGUFError, capabilities, header


def _s(text: str) -> bytes:
    data = text.encode()
    return struct.pack("<Q", len(data)) + data


def _gguf(path: Path, kv: dict[str, object]) -> Path:
    body = b""
    for key, value in kv.items():
        body += _s(key)
        if isinstance(value, bool):
            body += struct.pack("<I?", 7, value)
        elif isinstance(value, int):
            body += struct.pack("<IQ", 10, value)
        elif isinstance(value, list):                 # a string array, like a vocabulary
            body += struct.pack("<IIQ", 9, 8, len(value)) + b"".join(_s(v) for v in value)
        else:
            body += struct.pack("<I", 8) + _s(str(value))
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv)) + body)
    return path


def test_reads_what_the_model_and_its_projector_can_do(tmp_path: Path) -> None:
    model = _gguf(tmp_path / "m.gguf", {"general.architecture": "gemma4", "gemma4.context_length": 131072,
                                        "tokenizer.ggml.tokens": ["a", "b"],
                                        "tokenizer.chat_template": "{% if enable_thinking %}...{% endif %}"})
    proj = _gguf(tmp_path / "mmproj.gguf", {"clip.has_vision_encoder": True, "clip.has_audio_encoder": False})
    assert capabilities(model, proj) == {"vision": True, "audio": False, "thinking": True, "context": 131072}
    assert capabilities(model, None)["vision"] is False


def test_no_template_is_unknown_and_a_plain_one_is_no(tmp_path: Path) -> None:
    assert capabilities(_gguf(tmp_path / "a.gguf", {"general.architecture": "x"}), None)["thinking"] is None
    plain = _gguf(tmp_path / "b.gguf", {"tokenizer.chat_template": "{{ messages }}"})
    assert capabilities(plain, None)["thinking"] is False


def test_a_hostile_header_is_refused_not_read(tmp_path: Path) -> None:
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + struct.pack("<Q", 1 << 40))  # a 1 TB key
    with pytest.raises(GGUFError):
        header(bad)
    assert capabilities(bad, None) == {"vision": None, "audio": None, "thinking": None, "context": None}
    (tmp_path / "not.gguf").write_bytes(b"PK\x03\x04")
    with pytest.raises(GGUFError):
        header(tmp_path / "not.gguf")

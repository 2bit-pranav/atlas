"""What a model can do, read from its GGUF headers: no loading, no GPU.

- vision / audio: the projector file's own flags (`clip.has_vision_encoder`,
  `clip.has_audio_encoder`). No projector, neither.
- thinking: the chat template takes `enable_thinking` (Gemma, Qwen and most
  current models). A heuristic: a template without it is "no", no template is
  unknown (None).
- context: the longest context the model was trained for.

Model files come from the internet: every length read is capped, only the
header is read, and the template is searched as text, never run.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

_MAX_STRING = 1 << 20      # a chat template is ~20 KB; anything near 1 MB is not a real header string
_MAX_COUNT = 1 << 24       # vocabularies are ~260k entries
_SCALAR = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


class GGUFError(ValueError):
    """Not a GGUF file, or a header that breaks the caps."""


def _u64(f: BinaryIO) -> int:
    data = f.read(8)
    if len(data) != 8:
        raise GGUFError("truncated header")
    return struct.unpack("<Q", data)[0]


def _string(f: BinaryIO, keep: bool) -> str | None:
    n = _u64(f)
    if n > _MAX_STRING:
        raise GGUFError("header string too long")
    if not keep:
        f.seek(n, 1)
        return None
    return f.read(n).decode("utf-8", "replace")


def _value(f: BinaryIO, kind: int, keep: bool) -> Any:
    if kind == 8:
        return _string(f, keep)
    if kind == 9:
        inner, count = struct.unpack("<IQ", f.read(12))
        if count > _MAX_COUNT:
            raise GGUFError("header array too long")
        if inner == 8:
            for _ in range(count):
                _string(f, False)
        elif inner in _SCALAR:
            f.seek(struct.calcsize("<" + _SCALAR[inner]) * count, 1)
        else:
            raise GGUFError("unsupported array type")
        return None
    if kind not in _SCALAR:
        raise GGUFError(f"unknown value type {kind}")
    fmt = "<" + _SCALAR[kind]
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def header(path: Path) -> dict[str, Any]:
    """The header's scalar and string values (arrays are skipped)."""
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise GGUFError("not a GGUF file")
        f.read(4)                                   # version
        _u64(f)                                     # tensor count
        count = _u64(f)
        if count > 100_000:
            raise GGUFError("too many header keys")
        out: dict[str, Any] = {}
        for _ in range(count):
            key = _string(f, True) or ""
            kind = struct.unpack("<I", f.read(4))[0]
            value = _value(f, kind, keep=True)
            if value is not None:
                out[key] = value
        return out


@lru_cache(maxsize=32)
def _capabilities(model: str, model_stamp: tuple[int, int], mmproj: str | None,
                  mmproj_stamp: tuple[int, int] | None) -> dict[str, Any]:
    weights = header(Path(model))
    template = weights.get("tokenizer.chat_template")
    arch = weights.get("general.architecture", "")
    context = weights.get(f"{arch}.context_length")
    projector = header(Path(mmproj)) if mmproj else {}
    return {
        "vision": bool(projector.get("clip.has_vision_encoder")),
        "audio": bool(projector.get("clip.has_audio_encoder")),
        "thinking": None if not isinstance(template, str) else "enable_thinking" in template,
        "context": int(context) if isinstance(context, int) else None,
    }


def capabilities(model: Path, mmproj: Path | None) -> dict[str, Any]:
    """{vision, audio, thinking, context} for a model and its projector, cached per file version.
    An unreadable file says nothing (every value unknown) rather than failing the caller."""
    stamp = lambda p: (p.stat().st_size, p.stat().st_mtime_ns)  # noqa: E731
    try:
        return _capabilities(str(model), stamp(model), str(mmproj) if mmproj else None,
                             stamp(mmproj) if mmproj else None)
    except (OSError, GGUFError, struct.error):
        return {"vision": None, "audio": None, "thinking": None, "context": None}


__all__ = ["GGUFError", "capabilities", "header"]

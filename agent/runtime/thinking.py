"""Whether a turn thinks first, chosen by code (plan 3.8).

Thinking roughly doubles a turn's generated tokens (86% of model time is
generation, 2026-11-12), and helps only where there is a plan to make: several
files, or a document to produce. A question, a single read or a chat answer
gets nothing from it. The composer's switch overrides this (Auto, On, Off).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent.runtime.skill_tools import _NAMED

#: Asked to make something: a creation word, then within the sentence a document type or file name.
_MAKE = re.compile(r"\b(?:make|create|write|save|export|produce|generate|build|turn|convert|put|compile|draft|"
                   r"merge|combine|fill|rewrite|reorganise|reorganize)\b(?:[^.\n?]|\.(?=\w)){0,80}", re.I)
_FILE = re.compile(r"\.(?:docx?|xlsx?|pdf|csv|pptx)\b|\b(?:document|report|table|sheet|summary)\b", re.I)


def wants_thinking(text: str, files: Sequence[str] = ()) -> bool:
    """True for a turn with several files, or one that asks for a document to be made."""
    if len([f for f in files if f]) >= 2:
        return True
    for m in _MAKE.finditer(text or ""):
        span = m.group(0)
        if _FILE.search(span) or any(p.search(span) for p, _ in _NAMED):
            return True
    return False


__all__ = ["wants_thinking"]

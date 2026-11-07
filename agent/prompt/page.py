"""The page that comes with a message sent from the browser extension.

The panel sends the page's content with the message (`Page.content`: a
Google file's text, an article, or the page's accessibility tree, built in
the browser), so the model answers in its first call instead of spending a
tool call, and a model turn, on reading it. Everything here is page content:
marked as data, not instructions, and the run is tainted before it starts.

A page already sent earlier in the chat, unchanged, is not sent again: the
model already has it, and resending it would fill the context turn by turn.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.tools.page import UNTRUSTED

#: Up to this much of the page goes in the message; the rest is in a file.
INLINE_CHARS = 12_000

_INTRO = {
    "selection": "The part of the page around the passage the user selected:",
    "document": "The Google Doc's text:",
    "spreadsheets": "The Google Sheet's open tab, as CSV:",
    "presentation": "The Google Slides deck's text:",
    "pdf": "The PDF's text:",
}

_HOW = ("Answer from the page. Back each statement about it with a short exact quote in double quotes, "
        "so it can be highlighted for the user. Links and controls appear as [name](e12): to show the "
        'user one, call page_show("e12"). page_find searches the page; page_screenshot looks at it '
        "when what matters is an image.")


def page_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()


def head(content: str, limit: int = INLINE_CHARS) -> str:
    """The first `limit` characters, cut at a line."""
    if len(content) <= limit:
        return content
    cut = content.rfind("\n", 0, limit)
    return content[: cut if cut > limit // 2 else limit]


def page_note(page: dict[str, Any], *, already_sent: bool = False, saved_as: str | None = None) -> str:
    """What the model is told about the page, after the user's own text."""
    title = str(page.get("title") or "").strip()
    url = str(page.get("url") or "").strip()
    content = str(page.get("content") or "").strip()
    kind = str(page.get("kind") or "page")
    where = f'the web page "{title}" ({url})'
    if kind == "drive-file":
        return f"[The user is looking at {where}, a file on Google Drive; it is attached to this message.]"
    if not content:
        # An older panel, or a page that could not be read in the browser.
        return (f"[The user is looking at {where}. Read it with page_read; find passages with page_find; "
                "look at it with page_screenshot when the content is an image. Back each statement about "
                "the page with a short exact quote in double quotes, so it can be highlighted for the user.]")
    if already_sent:
        return f"[The user is still on {where}. Its content has not changed since it was given earlier in this chat. {_HOW}]"
    body = head(content)
    rest = (f"\n(The page is longer: all of it is in {saved_as}. Search it with page_find, or read the file.)"
            if saved_as and len(body) < len(content) else "")
    intro = _INTRO.get(kind, "The page, as text and its links and controls:")
    return (f"[The user is looking at {where}.]\n{UNTRUSTED}{intro}\n<page>\n{body}{rest}\n</page>\n[{_HOW}]")


__all__ = ["INLINE_CHARS", "head", "page_hash", "page_note"]

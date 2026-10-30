"""The note added to a message sent from the extension with a page attached."""

from __future__ import annotations

from typing import Any


#: Added to the user's message when it comes from the extension with a page attached.
def page_note(page: dict[str, Any]) -> str:
    title = str(page.get("title") or "").strip()
    url = str(page.get("url") or "").strip()
    return (f'[The user is looking at the web page "{title}" ({url}). Read it with page_read; '
            "find passages with page_find; look at it with page_screenshot when the content is an "
            "image. Back each statement about the page with a short exact quote from it in double "
            'quotes, so it can be highlighted for the user.]')


__all__ = ["page_note"]

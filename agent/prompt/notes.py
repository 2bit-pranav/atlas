"""Notes added to a message for the model only: the clock, and a retry's hint."""

from __future__ import annotations

from datetime import datetime

from agent.config.settings import Settings
from agent.model.sampling import RetryPlan


def retry_hint(settings: Settings, retry: RetryPlan) -> str:
    """The note appended to a retried question, quoting what came before.

    Appended to the *user message*, not the system prompt: the system prompt is
    the start of the cached prefix, so changing it would make llama-server
    re-read the whole conversation, and a small model also pays more attention
    to the last thing it was told. The run removes it from history before the
    snapshot is saved, so follow-ups never see it.
    """
    r = settings.retry
    lines = [r.instructions.strip()] if r.instructions.strip() else []
    if r.show_previous:
        for i, text in enumerate(retry.previous[: r.previous_limit], start=1):
            excerpt = " ".join(text.split())[: r.previous_chars]
            if excerpt:
                lines.append(f'Earlier answer {i}: "{excerpt}"')
    return "\n".join(lines)


def clock_note(now: datetime | None = None) -> str:
    """The send time appended to every user message: local time and its offset."""
    now = (now or datetime.now()).astimezone()
    offset = now.strftime("%z")
    # Worded as context, not a line to copy: shorter, the model echoed it.
    return f"[Context, not to repeat: sent {now:%a %d %b %Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})]"


__all__ = ["clock_note", "retry_hint"]

"""Asking the user before the agent installs anything.

The model may install packages -- an npm-based skill is useless otherwise --
but never silently. Any shell command that installs (pip, npm, npx, winget,
...) pauses the run and asks the user in the chat: Allow or Deny. No answer
within `approvals.timeout` seconds counts as Deny, and so does cancelling the
run, so a closed tab can never leave the agent waiting forever.

The hook only decides *whether* to ask. Asking is the run's job
(`server.runs.Run.request_approval`): it emits an event the UI renders as a
card and waits for `POST /api/runs/{id}/approvals/{approval_id}`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolCallEvent

logger = logging.getLogger(__name__)

#: `(kind, detail) -> "allowed" | "denied" | "expired"`
Approver = Callable[[str, dict[str, Any]], Awaitable[str]]

#: A command that installs something, at the start of the command or after a
#: separator (`cd x && npm install y`).
_INSTALL = re.compile(
    r"(?:^|[;&|(]\s*|\bsudo\s+)"
    r"(?:"
    r"(?:python3?|py)(?:\.exe)?\s+-m\s+pip\s+install"
    r"|pip3?(?:\.exe)?\s+install"
    r"|uv\s+(?:pip\s+install|add|tool\s+install)"
    r"|uvx\b"
    r"|npm\s+(?:i|install|add|ci)\b"
    r"|npx\b"
    r"|pnpm\s+(?:add|install|i|dlx)\b"
    r"|yarn\s+(?:add|global\s+add|dlx)\b"
    r"|bunx?\s+(?:add|install|i)?\b"
    r"|conda\s+install|mamba\s+install"
    r"|winget\s+install|choco\s+install|scoop\s+install"
    r"|apt(?:-get)?\s+install|brew\s+install"
    r"|cargo\s+install|go\s+install|gem\s+install"
    r")",
    re.IGNORECASE,
)


def is_install(command: str) -> bool:
    return bool(_INSTALL.search(command or ""))


class InstallApproval(HookProvider):
    """Pause installing shell commands until the user allows them."""

    def __init__(self, approver: Approver | None) -> None:
        self.approver = approver

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)

    async def _before(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use
        if use.get("name") != "shell":
            return
        command = str((use.get("input") or {}).get("command", ""))
        if not is_install(command):
            return
        if self.approver is None:
            event.cancel_tool = ("Installing needs the user's approval, and there is no one to ask "
                                 "here. Tell the user the exact command to run themselves.")
            return
        decision = await self.approver("install", {"tool": "shell", "command": command})
        logger.info("install %s: %s", decision, command)
        if decision == "allowed":
            return
        if decision == "expired":
            event.cancel_tool = ("The user did not answer the install request in time, so it was "
                                 "not run. Do not retry it. Tell the user what you wanted to install "
                                 "and why, and that they can ask you again.")
        else:
            event.cancel_tool = ("The user declined this install, so it was not run. Do not try to "
                                 "install it another way. Continue without it, or explain what it "
                                 "was needed for.")


__all__ = ["Approver", "InstallApproval", "is_install"]

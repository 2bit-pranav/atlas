"""ContextBuilder v0 (spec sections 9 and 10).

Turns a chat's visible node path into Strands messages.

Deliberately minimal for L3: no pruning, no summarisation, no budget arithmetic,
no attachment descriptions. What it does get right now is the part every later
layer depends on:

* **Structure comes from the database, not from the agent's own history.**
  Strands is stateless per run (section 9), so this is the only way a branch
  gets the right conversation.
* **Thinking is never replayed.** Section 10 is explicit, and it is also what
  the Gemma chat template does with older reasoning anyway.
* **Tool calls and tool results stay paired.** Stripping one without the other
  would leave an orphan and break the template, so a run of tool steps is
  emitted as assistant(toolUse) followed by user(toolResult).
"""

from __future__ import annotations

from typing import Any

from agent.core.repo import Node, Repo, Step


class ContextBuilder:
    """DB path -> Strands messages."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    def build(self, chat_id: str) -> list[dict[str, Any]]:
        """Messages for the whole visible path."""
        messages: list[dict[str, Any]] = []
        for node in self.repo.visible_path(chat_id):
            if node.role == "root":
                continue
            if node.role == "user":
                message = self._user_message(node)
                if message:
                    messages.append(message)
            elif node.role == "assistant":
                messages.extend(self._assistant_messages(node))
        return self._merge_tool_results(messages)

    def build_for_run(self, run_user_node_id: str) -> list[dict[str, Any]]:
        """Messages up to and including the user node this run answers.

        The run's own assistant node is at the end of the visible path but has
        no steps yet, so slicing the path is clearer than relying on that.
        """
        messages: list[dict[str, Any]] = []
        for node in self.repo.visible_path_to(run_user_node_id):
            if node.role == "root":
                continue
            if node.role == "user":
                message = self._user_message(node)
                if message:
                    messages.append(message)
            elif node.role == "assistant":
                messages.extend(self._assistant_messages(node))
        return self._merge_tool_results(messages)

    # ----------------------------------------------------------- node kinds --

    def _user_message(self, node: Node) -> dict[str, Any] | None:
        content = node.content if isinstance(node.content, dict) else {}
        blocks: list[str] = []
        attachment_ids: list[str] = []
        for block in content.get("blocks", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                blocks.append(str(block["text"]))
            elif block.get("type") == "attachment":
                attachment_ids.append(str(block.get("attachment_id", "")))

        for line in self._attachment_lines(attachment_ids):
            blocks.append(line)

        if not blocks:
            return None
        return {"role": "user", "content": [{"text": "\n\n".join(blocks)}]}

    def _attachment_lines(self, attachment_ids: list[str]) -> list[str]:
        """Attachments named the way the tools want them: handle first.

        This used to render the raw attachment id. Measured on the real model,
        that is actively harmful: shown ``[attachment 01M4MX5X9DQF8N0MCJFT2SCDWJ]``
        the model passed that id straight to ``outline``, and every tool wants a
        handle instead. The id is still printed, but after the handle and the
        filename, so the id is something the model can fall back on rather than
        the first thing it reaches for.
        """
        if not attachment_ids:
            return []
        try:
            states = self.repo.attachment_states(attachment_ids)
        except Exception:  # noqa: BLE001 - a rendering nicety is not worth a run
            return [f"[attachment {aid}]" for aid in attachment_ids]

        lines: list[str] = []
        for aid in attachment_ids:
            state = states.get(aid)
            if not state:
                continue
            name = state.get("name") or "?"
            handle = state.get("handle") or "?"
            status = state.get("status")
            if status == "ready":
                lines.append(f"[attachment {handle}: {name}]")
            else:
                # Say so here too. The run's settle step normally covers this,
                # but a file that failed to parse is ready-never, and the model
                # should not treat a broken attachment as an empty one.
                lines.append(f"[attachment {handle}: {name} - {status}, not readable]")
        return lines

    def _assistant_messages(self, node: Node) -> list[dict[str, Any]]:
        """Assistant blocks, with thinking dropped (section 10)."""
        blocks: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []

        for step in self.repo.steps(node.id):
            if step.kind == "thinking":
                continue
            if step.kind == "text":
                text = self._step_text(step.content)
                if text:
                    blocks.append({"text": text})
            elif step.kind == "tool_call":
                call = self._tool_use(step)
                if call:
                    blocks.append({"toolUse": call})
            elif step.kind == "tool_result":
                result = self._tool_result(step)
                if result:
                    results.append({"toolResult": result})

        out: list[dict[str, Any]] = []
        if blocks:
            out.append({"role": "assistant", "content": blocks})
        if results:
            out.append({"role": "user", "content": results})
        return out

    # ---------------------------------------------------------------- steps --

    @staticmethod
    def _step_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return content["text"]
            parts = content.get("blocks") or []
            return "\n".join(
                str(b.get("text", "")) for b in parts if isinstance(b, dict)
            ).strip()
        return ""

    def _tool_use(self, step: Step) -> dict[str, Any] | None:
        content = step.content if isinstance(step.content, dict) else {}
        name = content.get("name")
        if not name:
            return None
        return {
            "toolUseId": step.call_id or step.id,
            "name": str(name),
            "input": content.get("input") or {},
        }

    def _tool_result(self, step: Step) -> dict[str, Any] | None:
        content = step.content if isinstance(step.content, dict) else {}
        text = self._step_text(content)
        return {
            "toolUseId": step.call_id or "",
            "status": "error" if step.is_error else "success",
            "content": [{"text": text if text else "(no output)"}],
        }

    # ------------------------------------------------------------- pairing --

    def _merge_tool_results(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Fold consecutive tool-result messages into one, and drop orphans.

        A tool result whose call is missing would be an orphan; the spec forbids
        that ("tool calls and results stay paired"), so it is dropped rather
        than sent to the model.
        """
        out: list[dict[str, Any]] = []
        for message in messages:
            blocks = message.get("content", [])
            if blocks and all("toolResult" in b for b in blocks):
                if out and out[-1]["role"] == "user" and all(
                    "toolResult" in b for b in out[-1].get("content", [])
                ):
                    out[-1]["content"].extend(blocks)
                    continue
            out.append(message)

        return [m for m in out if not self._is_orphan(m, out)]

    @staticmethod
    def _is_orphan(message: dict[str, Any], all_messages: list[dict[str, Any]]) -> bool:
        """A user message of only tool results with no preceding tool use."""
        blocks = message.get("content", [])
        if not blocks or not all("toolResult" in b for b in blocks):
            return False
        index = all_messages.index(message)
        if index == 0:
            return True
        previous = all_messages[index - 1]
        prev_blocks = previous.get("content", [])
        return not any("toolUse" in b for b in prev_blocks)


__all__ = ["ContextBuilder"]

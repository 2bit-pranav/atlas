"""`AtlasLlamaCppModel`: the stock `LlamaCppModel`, fixed for llama-server.

1. **Thinking.** The stock model builds the request body from a whitelist of
   keys, silently dropping `chat_template_kwargs`. Without this override
   `enable_thinking=False` never reaches the server, and the template's own
   default (thinking on) wins.
2. **Reasoning out.** `delta.reasoning_content` (or `<think>` text) is
   forwarded as a `reasoning_content` chunk, so Atlas shows thinking apart
   from the answer.
3. **Reasoning back in.** `reasoningContent` blocks are sent as each assistant
   message's `reasoning_content` (see `_format_messages`).
4. **Real streaming.** `client.stream(...)`: a plain `client.post(...)` makes
   httpx buffer the whole body, so every model call arrived in one burst.
5. **Stats.** llama-server's `timings` go to `observer` for the context meter
   and per-turn stats, per token so the meter moves while generating.
6. **Documents.** `document` blocks, which llama-server rejects, become a text
   note (`_sendable`).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator, Callable

from strands.models.llamacpp import (
    ContextWindowOverflowException,
    LlamaCppModel,
    ModelThrottledException,
    warn_on_tool_choice_not_supported,
)
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from agent.core.llama import auth_headers
import httpx

logger = logging.getLogger(__name__)


class AtlasLlamaCppModel(LlamaCppModel):
    """A `LlamaCppModel` that handles thinking and streams reasoning_content.

    Args:
        enable_thinking: sent on every request. Always explicit, because the
            server defaults to ON and an omitted flag means "think".
        base_url: llama-server endpoint.
        params: sampler settings, passed through unchanged.
    """

    def __init__(
        self,
        *,
        base_url: str,
        enable_thinking: bool = False,
        context_window_limit: int = 32768,
        params: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        observer: Callable[[dict[str, Any]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            base_url=base_url,
            context_window_limit=context_window_limit,
            params=params or {},
            **kwargs,
        )
        self.client.headers.update(auth_headers())
        self._enable_thinking = enable_thinking
        #: Request keys the base class's whitelist would drop (`timings_per_token`).
        self._extra_body = dict(extra_body or {})
        #: Called with `{"type": "call_start"}` and `{"type": "timings", ...}`.
        self.observer = observer

    def set_thinking(self, enabled: bool) -> None:
        """Called per turn from the live setting, so no restart is needed."""
        self._enable_thinking = bool(enabled)

    @property
    def thinking_enabled(self) -> bool:
        return self._enable_thinking

    def _format_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Add the key the base class drops."""
        request = super()._format_request(*args, **kwargs)
        request["chat_template_kwargs"] = {"enable_thinking": self._enable_thinking}
        request.update(self._extra_body)
        return request

    def _format_messages(self, messages: Messages, system_prompt: str | None = None) -> list[dict[str, Any]]:
        """Send reasoning back as `reasoning_content`, and let the template choose.

        Strands keeps a `reasoningContent` block in each assistant message. The
        base formatter raises on it (`content_type=<reasoningContent> |
        unsupported type`), so it must come out of `content` -- but it must not
        be thrown away. Gemma's chat template renders the reasoning of the
        *current* turn's steps and drops earlier turns' by itself (measured with
        `/apply-template`). Stripping it all made the model forget its own plan
        after every tool call: it restated the task, reloaded the same skill
        and re-ran the same tool, three times in one turn.

        Messages are formatted one at a time, which is how the base formatter
        treats them anyway, so each one's reasoning lands on its own message.
        """
        out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}] if system_prompt else []
        for m in messages:
            blocks = m.get("content") or []
            thought = "".join(_reasoning_of(b) for b in blocks)
            kept = {**m, "content": [_sendable(b) for b in blocks if "reasoningContent" not in b]}
            formatted = super()._format_messages([kept], None)
            if thought and formatted and formatted[0].get("role") == "assistant":
                formatted[0]["reasoning_content"] = thought
            out.extend(formatted)
        return out

    def _observe(self, event: dict[str, Any]) -> None:
        if self.observer is not None:
            try:
                self.observer(event)
            except Exception:  # noqa: BLE001 - stats must never break a run
                logger.debug("observer failed", exc_info=True)

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream conversation with llama.cpp, capturing reasoning_content."""
        warn_on_tool_choice_not_supported(tool_choice)
        start_time = time.perf_counter()

        try:
            request = self._format_request(messages, tool_specs, system_prompt)
            self._observe({"type": "call_start"})
            async with self.client.stream("POST", "/v1/chat/completions", json=request) as response:
                if response.status_code >= 400:
                    # A streamed response has no body yet; read it so the error
                    # handler below can report llama-server's own message.
                    await response.aread()
                    response.raise_for_status()
                async for chunk in self._stream_body(response, start_time):
                    yield chunk

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                try:
                    error_data = e.response.json()
                    error_msg = str(error_data.get("error", {}).get("message", str(error_data)))
                except Exception:
                    error_msg = e.response.text
                if any(term in error_msg.lower() for term in ["context", "kv cache", "slot"]):
                    raise ContextWindowOverflowException(f"Context window exceeded: {error_msg}") from e
            elif e.response.status_code == 503:
                raise ModelThrottledException("llama.cpp server is busy or overloaded") from e
            raise
        # Anything else propagates unchanged; resilience.py decides what is
        # worth retrying. (A substring test for "rate" would also match
        # "generate" and turn ordinary errors into throttling.)

    async def _stream_body(
        self, response: httpx.Response, start_time: float
    ) -> AsyncGenerator[StreamEvent, None]:
        """Turn llama-server's SSE lines into Strands stream events, as they arrive."""
        yield self._format_chunk({"chunk_type": "message_start"})
        yield self._format_chunk({"chunk_type": "content_start", "data_type": "text"})

        tool_calls: dict[int, list] = {}
        usage_data = None
        finish_reason = None
        in_think_tag = False

        async for line in response.aiter_lines():
            if not line.strip() or not line.startswith("data: "):
                continue

            data_content = line[6:]
            if data_content.strip() == "[DONE]":
                break

            try:
                event = json.loads(data_content)
            except json.JSONDecodeError:
                continue

            if isinstance(event.get("timings"), dict):
                self._observe({"type": "timings", **event["timings"]})

            # Usage can ride on a chunk that also carries the finish reason, so
            # only skip the chunk when usage is all it has.
            if event.get("usage"):
                usage_data = event["usage"]

            if not event.get("choices"):
                continue

            choice = event["choices"][0]
            delta = choice.get("delta", {})

            reasoning = delta.get("reasoning_content")
            if reasoning:
                yield self._format_chunk(
                    {
                        "chunk_type": "content_delta",
                        "data_type": "reasoning_content",
                        "data": reasoning,
                    }
                )

            content = delta.get("content")
            if content:
                # Fallback for reasoning left inline as <think>...</think>
                # rather than sent as reasoning_content.
                if "<think>" in content and not in_think_tag:
                    in_think_tag = True
                    before, _, after = content.partition("<think>")
                    if before:
                        yield self._format_chunk(
                            {
                                "chunk_type": "content_delta",
                                "data_type": "text",
                                "data": before,
                            }
                        )
                    content = after

                if in_think_tag:
                    if "</think>" in content:
                        think_text, _, rest = content.partition("</think>")
                        in_think_tag = False
                        if think_text:
                            yield self._format_chunk(
                                {
                                    "chunk_type": "content_delta",
                                    "data_type": "reasoning_content",
                                    "data": think_text,
                                }
                            )
                        if rest:
                            yield self._format_chunk(
                                {
                                    "chunk_type": "content_delta",
                                    "data_type": "text",
                                    "data": rest,
                                }
                            )
                    else:
                        yield self._format_chunk(
                            {
                                "chunk_type": "content_delta",
                                "data_type": "reasoning_content",
                                "data": content,
                            }
                        )
                else:
                    yield self._format_chunk(
                        {
                            "chunk_type": "content_delta",
                            "data_type": "text",
                            "data": content,
                        }
                    )

            if "tool_calls" in delta:
                for tool_call in delta["tool_calls"]:
                    index = tool_call["index"]
                    if index not in tool_calls:
                        tool_calls[index] = []
                    tool_calls[index].append(tool_call)

            if choice.get("finish_reason"):
                finish_reason = choice.get("finish_reason")

        yield self._format_chunk({"chunk_type": "content_stop"})

        for tool_deltas in tool_calls.values():
            first_delta = tool_deltas[0]
            yield self._format_chunk(
                {
                    "chunk_type": "content_start",
                    "data_type": "tool",
                    "data": type(
                        "ToolCall",
                        (),
                        {
                            "function": type(
                                "Function",
                                (),
                                {
                                    "name": first_delta.get("function", {}).get("name", ""),
                                },
                            )(),
                            "id": first_delta.get("id", ""),
                        },
                    )(),
                }
            )

            for tool_delta in tool_deltas:
                yield self._format_chunk(
                    {
                        "chunk_type": "content_delta",
                        "data_type": "tool",
                        "data": type(
                            "ToolCall",
                            (),
                            {
                                "function": type(
                                    "Function",
                                    (),
                                    {
                                        "arguments": tool_delta.get("function", {}).get("arguments", ""),
                                    },
                                )(),
                            },
                        )(),
                    }
                )

            yield self._format_chunk({"chunk_type": "content_stop"})

        stop_reason = "tool_calls" if (finish_reason == "tool_calls" or tool_calls) else (finish_reason or "end_turn")
        yield self._format_chunk({"chunk_type": "message_stop", "data": stop_reason})

        if usage_data:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            cached_tokens = (usage_data.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            yield self._format_chunk(
                {
                    "chunk_type": "metadata",
                    "data": type(
                        "Usage",
                        (),
                        {
                            "prompt_tokens": usage_data.get("prompt_tokens", 0),
                            "completion_tokens": usage_data.get("completion_tokens", 0),
                            "total_tokens": usage_data.get("total_tokens", 0),
                            "cached_tokens": cached_tokens,
                        },
                    )(),
                    "latency_ms": latency_ms,
                }
            )


def _reasoning_of(block: Any) -> str:
    if not isinstance(block, dict) or "reasoningContent" not in block:
        return ""
    inner = block["reasoningContent"] or {}
    text = (inner.get("reasoningText") or {}).get("text") if isinstance(inner, dict) else None
    return str(text or "")


def _sendable(block: Any) -> Any:
    """Replace `document` blocks, which llama-server rejects with a 400.

    The harness `read` tool returns a pdf, docx or xlsx as a `document` block,
    meant for cloud models that can view one. llama.cpp cannot, and the whole
    request fails -- so the model is told what it tried to read and pointed at
    the skill that can. Images are left alone: those the model can see.
    """
    if not isinstance(block, dict):
        return block
    if "document" in block:
        doc = block["document"] or {}
        return {"text": f"[{doc.get('name', 'document')} is a binary {doc.get('format', '')} file and "
                        "cannot be shown directly. Read it with the matching skill's script instead.]"}
    if "toolResult" in block:
        result = block["toolResult"]
        return {"toolResult": {**result, "content": [_sendable(b) for b in result.get("content") or []]}}
    return block


__all__ = ["AtlasLlamaCppModel"]
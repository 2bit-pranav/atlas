"""`AtlasLlamaCppModel` (design.md L1, tests T1.1-T1.5).

Two jobs, and both exist because something upstream does not do what the docs
imply:

1. **Thinking.** The stock `LlamaCppModel` builds the request body by copying a
   whitelist of keys, so anything else is silently dropped -- including
   `chat_template_kwargs`. Without this override `enable_thinking=False` never
   reaches the server, and the template's own default wins.

2. **Reasoning passthrough.** `delta.reasoning_content` is forwarded as a
   `reasoning_content` chunk, which Strands' `_format_chunk` already converts to
   `contentBlockDelta.delta.reasoningContent`, allowing Atlas to display thinking
   separately from the answer.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator

from strands.models.llamacpp import (
    ContextWindowOverflowException,
    LlamaCppModel,
    ModelThrottledException,
    warn_on_tool_choice_not_supported,
)
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec
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
        **kwargs: Any,
    ) -> None:
        super().__init__(
            base_url=base_url,
            context_window_limit=context_window_limit,
            params=params or {},
            **kwargs,
        )
        self._enable_thinking = enable_thinking

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
        return request

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
            response = await self.client.post("/v1/chat/completions", json=request)
            response.raise_for_status()

            yield self._format_chunk({"chunk_type": "message_start"})
            yield self._format_chunk({"chunk_type": "content_start", "data_type": "text"})

            tool_calls: dict[int, list] = {}
            usage_data = None
            finish_reason = None
            in_think_tag = False
            think_buffer = ""

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

                if "usage" in event:
                    usage_data = event["usage"]
                    continue

                if not event.get("choices"):
                    continue

                choice = event["choices"][0]
                delta = choice.get("delta", {})

                # 1. Direct reasoning_content delta from llama.cpp / OpenAI format
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield self._format_chunk(
                        {
                            "chunk_type": "content_delta",
                            "data_type": "reasoning_content",
                            "data": reasoning,
                        }
                    )

                # 2. Content delta (with fallback <think>...</think> extraction)
                content = delta.get("content")
                if content:
                    # Check for inline <think> tags if reasoning_content is not used
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

                # Handle tool calls
                if "tool_calls" in delta:
                    for tool_call in delta["tool_calls"]:
                        index = tool_call["index"]
                        if index not in tool_calls:
                            tool_calls[index] = []
                        tool_calls[index].append(tool_call)

                if choice.get("finish_reason"):
                    finish_reason = choice.get("finish_reason")

            yield self._format_chunk({"chunk_type": "content_stop"})

            # Process tool calls
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

            # Send stop reason
            stop_reason = "tool_calls" if (finish_reason == "tool_calls" or tool_calls) else (finish_reason or "end_turn")
            yield self._format_chunk({"chunk_type": "message_stop", "data": stop_reason})

            # Send usage metadata if available
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
        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg or "429" in str(e):
                raise ModelThrottledException(str(e)) from e
            raise


__all__ = ["AtlasLlamaCppModel"]
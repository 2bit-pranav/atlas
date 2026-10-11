"""Atlas' llama.cpp model adapter.

Wraps Strands' built-in ``LlamaCppModel`` with the two fixes L0 found necessary
(section 16, spikes S1 and S2). Both are gaps in the upstream adapter, not in
llama-server, which is the point of this module: keep them isolated and
deletable.

S1 -- per-request ``thinking`` toggle.
    ``LlamaCppModel._format_request`` forwards params through a strict allowlist
    (``openai_params`` + ``llamacpp_specific_params``). ``chat_template_kwargs``
    is in neither, so ``model.update_config(params={"chat_template_kwargs": ...})``
    is silently dropped and the server falls back to its own default. We inject
    it after the fact so toggling thinking needs no server restart.

S2 -- reasoning was being thrown away.
    llama-server splits Gemma 3's ``<|channel|>thought`` block out of the
    completion and returns it as ``delta.reasoning_content``. Upstream
    ``stream()`` only reads ``delta.content`` and ``delta.tool_calls``, so the
    reasoning was discarded before it ever reached the agent -- even though
    ``_format_chunk`` already knows how to turn a ``reasoning_content`` chunk
    into a ``reasoningContent`` delta. We re-implement the SSE loop to forward
    it, which is what makes the spec's ``thinking_delta`` events possible.

Upstream fix to watch for: if ``LlamaCppModel.stream`` starts reading
``delta.reasoning_content`` and ``_format_request`` forwards
``chat_template_kwargs``, drop this subclass and use ``LlamaCppModel`` directly.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from strands.models.llamacpp import LlamaCppModel
from strands.types.content import Messages
from strands.types.exceptions import (
    ContextWindowOverflowException,
    ModelThrottledException,
)
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

logger = logging.getLogger(__name__)


class AtlasLlamaCppModel(LlamaCppModel):
    """``LlamaCppModel`` + per-request thinking toggle + reasoning passthrough.

    Extra constructor kwargs:
        chat_template_kwargs: dict merged into the request body every call, e.g.
            ``{"enable_thinking": True}``. Set ``False`` to force thinking off.
            Omit entirely to inherit whatever the server was started with.
    """

    def __init__(self, **kwargs: Any) -> None:
        chat_template_kwargs = kwargs.pop("chat_template_kwargs", None)
        super().__init__(**kwargs)
        self._atlas_chat_template_kwargs = chat_template_kwargs

    # ------------------------------------------------------------------ S1 --

    def _format_request(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        request = super()._format_request(messages, tool_specs, system_prompt)
        kwargs = self._atlas_chat_template_kwargs
        if kwargs:
            # Merged, not replaced: a caller may already have set params that
            # expand into the body.
            merged = dict(request.get("chat_template_kwargs") or {})
            merged.update(kwargs)
            request["chat_template_kwargs"] = merged
        return request

    def set_thinking(self, enabled: bool) -> None:
        """Toggle thinking for subsequent requests. No restart, no new agent."""
        current = dict(self._atlas_chat_template_kwargs or {})
        current["enable_thinking"] = bool(enabled)
        self._atlas_chat_template_kwargs = current

    # ------------------------------------------------------------------ S13 --

    def _format_message_content(self, content: Any) -> dict[str, Any]:  # type: ignore[override]
        """Drop reasoning blocks instead of crashing the run.

        Strands' llama.cpp formatter raises ``TypeError: content_type=
        <reasoningContent> | unsupported type`` for any block it does not know.
        Reasoning blocks are exactly what this model emits on the first turn of
        a tool-using run, so on turn two the model's *own* reasoning is replayed
        into the request and the run dies with ``EventLoopException``. Measured
        against the real model: a "total revenue in March" run failed outright.

        The block is a display artifact, not something the model can read back:
        llama.cpp has no field for it, and replaying the text would spend
        context re-stating what the model already decided. So it is removed and
        the conversation continues. The reasoning still reaches the user -- it is
        captured while streaming and written to ``steps`` as a thinking step.
        """
        if isinstance(content, dict) and "reasoningContent" in content:
            logger.debug("dropping a reasoningContent block from the request")
            return {"text": "", "type": "text"}
        return super()._format_message_content(content)

    def _format_messages(  # type: ignore[override]
        self, messages: Messages, system_prompt: str | None = None
    ) -> list[dict[str, Any]]:
        """Format messages, then remove the holes S13 leaves behind.

        Dropping a reasoning block leaves an empty ``{"text": ""}`` in the
        assistant turn. Some chat templates render that as a stray newline, and
        it is dead weight either way, so it goes.
        """
        formatted = super()._format_messages(messages, system_prompt)
        for message in formatted:
            content = message.get("content")
            if isinstance(content, list):
                message["content"] = [
                    block for block in content
                    if not (block.get("type") == "text" and not block.get("text"))
                ]
        return [m for m in formatted if m.get("content") or "tool_calls" in m]

    # ------------------------------------------------------------------ S2 --

    async def stream(  # type: ignore[override]
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Mirror of upstream ``stream()`` that also reads reasoning deltas.

        Kept line-for-line close to upstream so the two stay easy to diff.
        """
        start_time = time.perf_counter()

        request = self._format_request(messages, tool_specs, system_prompt)
        logger.debug("request=<%s>", request)

        try:
            response = await self.client.post("/v1/chat/completions", json=request)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self._raise_mapped(exc)

        yield self._format_chunk({"chunk_type": "message_start"})  # type: ignore[arg-type]
        yield self._format_chunk(
            {"chunk_type": "content_start", "data_type": "text"}  # type: ignore[arg-type]
        )

        tool_calls: dict[int, list] = {}
        usage_data = None
        finish_reason = None
        reasoning_open = False
        reasoning_closed = False

        try:
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

                if "usage" in event and event["usage"]:
                    usage_data = event["usage"]
                    continue

                if not event.get("choices"):
                    continue

                choice = event["choices"][0]
                delta = choice.get("delta", {})

                # --- S2: reasoning arrives before content; close its block
                # when the first text token shows up so the agent sees a
                # well-formed reasoning/text sequence.
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    if not reasoning_open:
                        reasoning_open = True
                        yield self._format_chunk(
                            {
                                "chunk_type": "content_start",
                                "data_type": "reasoning_content",
                            }  # type: ignore[arg-type]
                        )
                    yield self._format_chunk(
                        {
                            "chunk_type": "content_delta",
                            "data_type": "reasoning_content",
                            "data": reasoning,
                        }  # type: ignore[arg-type]
                    )
                    continue

                if delta.get("content"):
                    if reasoning_open and not reasoning_closed:
                        reasoning_closed = True
                        yield self._format_chunk({"chunk_type": "content_stop"})  # type: ignore[arg-type]
                        yield self._format_chunk(
                            {"chunk_type": "content_start", "data_type": "text"}  # type: ignore[arg-type]
                        )
                    yield self._format_chunk(
                        {
                            "chunk_type": "content_delta",
                            "data_type": "text",
                            "data": delta["content"],
                        }  # type: ignore[arg-type]
                    )

                if "tool_calls" in delta:
                    for tool_call in delta["tool_calls"]:
                        index = tool_call["index"]
                        tool_calls.setdefault(index, []).append(tool_call)

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
        except Exception as exc:  # noqa: BLE001
            self._raise_mapped(exc)

        if reasoning_open:
            yield self._format_chunk({"chunk_type": "content_stop"})  # type: ignore[arg-type]
            yield self._format_chunk(
                {"chunk_type": "content_start", "data_type": "text"}  # type: ignore[arg-type]
            )
        yield self._format_chunk({"chunk_type": "content_stop"})  # type: ignore[arg-type]

        # Tool calls are replayed after the text stream, as upstream does.
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
                                {"name": first_delta.get("function", {}).get("name", "")},
                            )(),
                            "id": first_delta.get("id", ""),
                        },
                    )(),
                }  # type: ignore[arg-type]
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
                                        "arguments": tool_delta.get("function", {}).get(
                                            "arguments", ""
                                        )
                                    },
                                )()
                            },
                        )(),
                    }  # type: ignore[arg-type]
                )
            yield self._format_chunk({"chunk_type": "content_stop"})  # type: ignore[arg-type]

        if finish_reason == "tool_calls" or tool_calls:
            stop_reason = "tool_calls"
        else:
            stop_reason = finish_reason or "end_turn"
        yield self._format_chunk(
            {"chunk_type": "message_stop", "data": stop_reason}  # type: ignore[arg-type]
        )

        # S6: usage rides in the trailing SSE frame; llama-server orders it
        # finish -> usage -> [DONE], so it must not be drained early.
        if usage_data:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            # Length of the prompt prefix llama.cpp reused from its KV cache.
            # L6's hysteresis pruning targets this number.
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
                }  # type: ignore[arg-type]
            )

    # --------------------------------------------------------------- errors --

    @staticmethod
    def _raise_mapped(exc: Exception) -> None:
        """Map transport errors onto the codes the rest of Atlas relies on."""
        text = str(exc).lower()
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 400 and ("context" in text or "exceed" in text or "n_ctx" in text):
            raise ContextWindowOverflowException(f"context window exceeded: {exc}") from exc
        if status == 503:
            raise ModelThrottledException(f"llama-server busy: {exc}") from exc
        raise exc


__all__ = ["AtlasLlamaCppModel"]

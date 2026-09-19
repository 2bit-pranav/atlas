import os
import re
import uuid
from pathlib import Path
from typing import Dict, Any, Tuple, List, Sequence, Optional, Mapping, AsyncGenerator
from autogen_core import FunctionCall, CancellationToken
from autogen_core.models import ModelInfo, CreateResult, LLMMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from server.services.settings_service import CloudProvider, get_effective_settings

try:
    import orjson

    def _json_loads(s: str | bytes):
        return orjson.loads(s)

    def _json_dumps(obj: Any) -> str:
        return orjson.dumps(obj).decode("utf-8")
except ImportError:
    import json

    def _json_loads(s: str | bytes):
        return json.loads(s)

    def _json_dumps(obj: Any) -> str:
        return json.dumps(obj)

try:
    import tiktoken
    tiktoken.model.MODEL_TO_ENCODING.update({
        os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf"): "cl100k_base",
    })
except Exception:
    pass

MODEL_INFO = ModelInfo(
    vision=True,
    function_calling=True,
    structured_output=True,
    json_output=True,
    family="unknown",
)
_THOUGHT_PREFIX = "<|agent_thought|>"
_TAG_CLEANER_RE = re.compile(
    r"<think>.*?</think>|<\|?channel\|?>\s*thought.*?<\|?channel\|?>|</?(?:think|tool_call|tool_response|channel)\|?>?",
    flags=re.DOTALL | re.IGNORECASE,
)
_DANGLING_TAG_RE = re.compile(
    r"<think>.*|<\|?channel\|?>\s*thought.*",
    flags=re.DOTALL | re.IGNORECASE,
)
_CALL_PATTERN_RE = re.compile(r"(?:<\|?tool_call\|?>?)?\s*call:([a-zA-Z0-9_]+)\s*\{")
_KV_PATTERN_RE = re.compile(r'([a-zA-Z_]\w*)\s*:\s*(?:<\|"\|>|")?(.*?)(?:<\|"\|>|"|\s*(?:,|$))', re.DOTALL)


def parse_gemma_args_string(raw_args: str) -> Dict[str, Any]:
    if not raw_args:
        return {}
    cleaned = raw_args.replace('<|"', '"').replace('"|>', '"').replace('<|', '').replace('|>', '')
    try:
        return _json_loads(f"{{{cleaned}}}")
    except Exception:
        pass
    result = {}
    for k, v in _KV_PATTERN_RE.findall(raw_args):
        k, v = k.strip(), v.strip().replace('<|"', '"').replace('"|>', '"').strip()
        v_lower = v.lower()
        if v_lower == "true":
            result[k] = True
        elif v_lower == "false":
            result[k] = False
        else:
            try:
                result[k] = _json_loads(v)
            except Exception:
                result[k] = v
    return result


def strip_thinking_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = _TAG_CLEANER_RE.sub("", text)
    cleaned = _DANGLING_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def extract_gemma_tool_calls(text: str) -> Tuple[List[FunctionCall], Optional[str]]:
    if not text:
        return [], text
    tool_calls = []
    clean_text = text
    matches = list(_CALL_PATTERN_RE.finditer(clean_text))
    for match in reversed(matches):
        func_name = match.group(1)
        start_brace_idx = match.end() - 1
        brace_count = 0
        end_brace_idx = -1
        in_quotes = False
        quote_char = None
        for i in range(start_brace_idx, len(clean_text)):
            char = clean_text[i]
            if char in ('"', "'") and (i == 0 or clean_text[i - 1] != '\\'):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif quote_char == char:
                    in_quotes = False
                    quote_char = None
            elif not in_quotes:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_brace_idx = i
                        break
        if end_brace_idx != -1:
            raw_args_body = clean_text[start_brace_idx + 1:end_brace_idx].strip()
            end_pos = end_brace_idx + 1
            after_call = clean_text[end_pos:]
            tag_match = re.match(r"\s*(?:<\|?/?tool_call\|?>?)", after_call)
            if tag_match:
                end_pos += tag_match.end()
            args_dict = parse_gemma_args_string(raw_args_body)
            tool_calls.append(
                FunctionCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=func_name,
                    arguments=_json_dumps(args_dict),
                )
            )
            clean_text = clean_text[:match.start()] + clean_text[end_pos:]
    tool_calls.reverse()
    cleaned = strip_thinking_tags(clean_text)
    return tool_calls, (cleaned if cleaned else None)


class GemmaStreamInterceptor:
    __slots__ = ("has_tools", "in_think", "is_buffering_tool", "tool_buffer")

    def __init__(self, has_tools: bool = False):
        self.has_tools = has_tools
        self.in_think = False
        self.is_buffering_tool = False
        self.tool_buffer = ""

    def process_chunk(self, chunk: str) -> List[str]:
        if not self.tool_buffer and not self.in_think and "<" not in chunk and "call:" not in chunk:
            return [chunk]
        if "<think>" in chunk:
            self.in_think = True
            chunk = chunk.replace("<think>", "")
        if "</think>" in chunk:
            self.in_think = False
            chunk = chunk.replace("</think>", "")
        if self.in_think:
            return [f"{_THOUGHT_PREFIX}{chunk}"]
        if self.has_tools:
            combined = self.tool_buffer + chunk
            if any(marker in combined for marker in ("<|tool_call", "<tool_call", "call:")):
                self.is_buffering_tool = True
                self.tool_buffer += chunk
                return []
        if self.is_buffering_tool:
            self.tool_buffer += chunk
            return []
        clean_chunk = strip_thinking_tags(chunk)
        return [clean_chunk] if clean_chunk else []

    def flush(self) -> List[Any]:
        if self.tool_buffer:
            calls, cleaned = extract_gemma_tool_calls(self.tool_buffer)
            self.tool_buffer = ""
            if calls:
                return [
                    CreateResult(
                        finish_reason="function_calls",
                        content=calls,
                    )
                ]
            if cleaned:
                return [cleaned]
        return []


class GemmaOpenAIChatCompletionClient(OpenAIChatCompletionClient):
    def __init__(self, *args, extra_create_args: Mapping[str, Any] = {}, **kwargs):
        self._default_extra_create_args = dict(extra_create_args)
        super().__init__(*args, **kwargs)

    def _merge_extra_create_args(self, extra_create_args: Mapping[str, Any]) -> Dict[str, Any]:
        merged = dict(self._default_extra_create_args)
        if extra_create_args:
            default_body = merged.get("extra_body", {})
            passed_body = extra_create_args.get("extra_body", {})
            if default_body or passed_body:
                merged_body = {**default_body, **passed_body}
                merged = {**merged, **extra_create_args, "extra_body": merged_body}
            else:
                merged.update(extra_create_args)
        return merged

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
        **kwargs: Any,
    ) -> CreateResult:
        merged_args = self._merge_extra_create_args(extra_create_args)
        result = await super().create(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=merged_args,
            cancellation_token=cancellation_token,
            **kwargs,
        )
        if isinstance(result.content, str):
            extracted_calls, cleaned = extract_gemma_tool_calls(result.content)
            if extracted_calls:
                return CreateResult(
                    finish_reason="function_calls",
                    content=extracted_calls,
                    usage=result.usage,
                    cached=result.cached,
                    logprobs=result.logprobs,
                    thought=result.thought,
                )
            if not cleaned and not tools:
                cleaned = "[Empty response generated by model]"
            return CreateResult(
                finish_reason=result.finish_reason,
                content=cleaned or "",
                usage=result.usage,
                cached=result.cached,
                logprobs=result.logprobs,
                thought=result.thought,
            )
        return result

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        merged_args = self._merge_extra_create_args(extra_create_args)
        interceptor = GemmaStreamInterceptor(has_tools=bool(tools))
        async for chunk in super().create_stream(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=merged_args,
            cancellation_token=cancellation_token,
            **kwargs,
        ):
            if isinstance(chunk, str):
                for clean_text in interceptor.process_chunk(chunk):
                    yield clean_text
            else:
                yield chunk
        for flushed_item in interceptor.flush():
            yield flushed_item


def get_local_model(
    thinking_budget: int = 0,
    temperature: Optional[float] = None,
    presence_penalty: float = 0.0,
    chat_id: Optional[str] = None,
) -> GemmaOpenAIChatCompletionClient:
    settings = get_effective_settings()
    local = settings.model.local
    is_thinking = thinking_budget > 0
    extra_body: Dict[str, Any] = {
        "top_p": local.top_p,
        "top_k": local.top_k,
        "thinking_budget": thinking_budget if is_thinking else 0,
        "chat_template_kwargs": {"enable_thinking": is_thinking},
    }
    if chat_id:
        extra_body["id_slot"] = abs(hash(chat_id)) % 8
    return GemmaOpenAIChatCompletionClient(
        model=local.name,
        base_url=local.base_url,
        api_key="not-needed",
        model_info=MODEL_INFO,
        temperature=local.temperature if temperature is None else temperature,
        presence_penalty=presence_penalty,
        extra_create_args={"extra_body": extra_body},
    )


def get_cloud_model(
    temperature: float = 0.2,
) -> OpenAIChatCompletionClient | AnthropicChatCompletionClient:
    cloud = get_effective_settings().model.cloud
    if not cloud.api_key:
        raise ValueError("Cloud API key is not configured or could not be decrypted.")
    if cloud.provider == CloudProvider.ANTHROPIC:
        return AnthropicChatCompletionClient(
            model=cloud.name,
            api_key=cloud.api_key,
            model_info=MODEL_INFO,
            temperature=temperature,
        )
    return OpenAIChatCompletionClient(
        model=cloud.name,
        base_url=cloud.base_url,
        api_key=cloud.api_key,
        model_info=MODEL_INFO,
        temperature=temperature,
    )
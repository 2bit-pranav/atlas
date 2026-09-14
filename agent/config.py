import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List, Sequence, Optional, Mapping, AsyncGenerator
from dotenv import load_dotenv
import uuid

from autogen_core import FunctionCall, CancellationToken
from autogen_core.models import (
    ModelInfo,
    CreateResult,
    LLMMessage,
)
from autogen_ext.models.openai import OpenAIChatCompletionClient

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

try:
    import tiktoken
    tiktoken.model.MODEL_TO_ENCODING.update({
        os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf"): "cl100k_base",
    })
except Exception:
    pass

LOCAL_MODEL_NAME: str = os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf")
LOCAL_BASE_URL: str = os.getenv("LOCAL_BASE_URL", "http://127.0.0.1:8000/v1")
CLOUD_MODEL_NAME: str = os.getenv("CLOUD_MODEL_NAME", "gemini-3.5-flash-lite")
CLOUD_BASE_URL: str = os.getenv("CLOUD_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
CLOUD_API_KEY: str = os.getenv("CLOUD_API_KEY", "")

MODEL_INFO: ModelInfo = ModelInfo(
    vision=True,
    function_calling=True,
    structured_output=True,
    json_output=True,
    family="unknown",
)

_THOUGHT_PREFIX = "<|agent_thought|>"


def parse_gemma_args_string(raw_args: str) -> Dict[str, Any]:
    if not raw_args:
        return {}
    cleaned = raw_args.replace('<|"', '"').replace('"|>', '"').replace('<|', '').replace('|>', '')
    try:
        return json.loads(f"{{{cleaned}}}")
    except Exception:
        pass
    result = {}
    kv_pattern = r'([a-zA-Z_]\w*)\s*:\s*(?:<\|"\|>|")?(.*?)(?:<\|"\|>|"|\s*(?:,|$))'
    for k, v in re.findall(kv_pattern, raw_args, re.DOTALL):
        k = k.strip()
        v = v.strip().replace('<|"', '"').replace('"|>', '"').strip()
        if v.lower() == "true":
            result[k] = True
        elif v.lower() == "false":
            result[k] = False
        else:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
    return result


def strip_thinking_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<\|?channel\|?>\s*thought.*?<\|?channel\|?>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<\|?channel\|?>\s*thought.*", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"</?(?:think|tool_call|tool_response|channel)\|?>?", "", cleaned)
    cleaned = re.sub(r"<\|?/?(?:think|tool_call|tool_response|channel)\|?>?", "", cleaned)
    return cleaned.strip()


def extract_gemma_tool_calls(text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not text:
        return [], text
    tool_calls = []
    clean_text = text
    call_pattern = r"(?:<\|?tool_call\|?>?)?\s*call:([a-zA-Z0-9_]+)\s*\{"
    matches = list(re.finditer(call_pattern, clean_text))
    for match in matches:
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
            full_raw_call = clean_text[match.start():end_brace_idx + 1]
            raw_args_body = clean_text[start_brace_idx + 1:end_brace_idx].strip()
            after_call = clean_text[end_brace_idx + 1:]
            tag_match = re.match(r"\s*(?:<\|?/?tool_call\|?>?)", after_call)
            if tag_match:
                full_raw_call += tag_match.group(0)
            args_dict = parse_gemma_args_string(raw_args_body)
            tool_calls.append({
                "name": func_name,
                "arguments": args_dict
            })
            clean_text = clean_text.replace(full_raw_call, "").strip()
    cleaned = strip_thinking_tags(clean_text)
    return tool_calls, (cleaned if cleaned else None)


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
        tools: Sequence[Any] = [],
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult:
        merged_args = self._merge_extra_create_args(extra_create_args)
        result = await super().create(
            messages=messages,
            tools=tools,
            json_output=json_output,
            extra_create_args=merged_args,
            cancellation_token=cancellation_token,
        )
        if isinstance(result.content, str):
            extracted_calls, cleaned = extract_gemma_tool_calls(result.content)
            if extracted_calls:
                function_calls = [
                    FunctionCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=tc["name"],
                        arguments=json.dumps(tc["arguments"]),
                    )
                    for tc in extracted_calls
                ]
                return CreateResult(
                    finish_reason="function_calls",
                    content=function_calls,
                    usage=result.usage,
                    cached=result.cached,
                    logprobs=result.logprobs,
                    thought=result.thought,
                )
            if not cleaned and not tools:
                cleaned = "[Empty response generated by model]"
            result.content = cleaned or ""
        return result

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[Any] = [],
        json_output: Optional[bool] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Any, None]:
        merged_args = self._merge_extra_create_args(extra_create_args)
        in_think_block = False
        async for chunk in super().create_stream(
            messages=messages,
            tools=tools,
            json_output=json_output,
            extra_create_args=merged_args,
            cancellation_token=cancellation_token,
        ):
            if isinstance(chunk, str):
                text = chunk
                if "<think>" in text:
                    in_think_block = True
                    text = text.replace("<think>", "")
                if "</think>" in text:
                    in_think_block = False
                    text = text.replace("</think>", "")

                if in_think_block:
                    yield f"{_THOUGHT_PREFIX}{text}"
                else:
                    yield text
            else:
                yield chunk


def get_local_model(
    thinking_budget: int = 0,
    temperature: float = 0.1,
    presence_penalty: float = 0.0,
    chat_id: Optional[str] = None,
) -> GemmaOpenAIChatCompletionClient:
    extra_body: Dict[str, Any] = {}

    if thinking_budget > 0:
        extra_body["reasoning_effort"] = "medium"
        extra_body["thinking_budget_tokens"] = thinking_budget
        extra_body["reasoning_budget"] = thinking_budget
        extra_body["chat_template_kwargs"] = {"enable_thinking": True}
    else:
        extra_body["reasoning_effort"] = "none"
        extra_body["thinking_budget_tokens"] = 0
        extra_body["reasoning_budget"] = 0
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    if chat_id:
        extra_body["id_slot"] = abs(hash(chat_id)) % 8

    return GemmaOpenAIChatCompletionClient(
        model=LOCAL_MODEL_NAME,
        base_url=LOCAL_BASE_URL,
        api_key="not-needed",
        model_info=MODEL_INFO,
        temperature=temperature,
        presence_penalty=presence_penalty,
        extra_create_args={"extra_body": extra_body},
    )


def get_cloud_model(temperature: float = 0.2) -> OpenAIChatCompletionClient:
    api_key = CLOUD_API_KEY or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise ValueError("Missing CLOUD_API_KEY or GOOGLE_API_KEY.")

    return OpenAIChatCompletionClient(
        model=CLOUD_MODEL_NAME,
        base_url=CLOUD_BASE_URL,
        api_key=api_key,
        model_info=MODEL_INFO,
        temperature=temperature,
    )
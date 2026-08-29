import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List, Sequence, Optional, Mapping
from dotenv import load_dotenv

from autogen_core import FunctionCall
from autogen_core.models import (
    ModelInfo,
    AssistantMessage,
    CreateResult,
    LLMMessage,
    RequestUsage,
)
from autogen_ext.models.openai import (
    OpenAIChatCompletionClient,
    _openai_client,
)

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

# Suppress the noisy "Model X not found. Using cl100k_base encoding." warning
# that tiktoken emits on every call because it doesn't know local .gguf names.
# We register the local model name as an alias for gpt-4o's encoding
# (which is cl100k_base anyway, so token counts stay accurate).
try:
    import tiktoken
    tiktoken.model.MODEL_TO_ENCODING.update({
        os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf"): "cl100k_base",
    })
except Exception:
    pass  # tiktoken not installed — AutoGen will handle it gracefully

LOCAL_MODEL_NAME: str = os.getenv(
    "LOCAL_MODEL_NAME",
    "gemma-4-E2B_q4_0-it.gguf"
)

LOCAL_BASE_URL: str = os.getenv(
    "LOCAL_BASE_URL",
    "http://127.0.0.1:8000/v1"
)

CLOUD_MODEL_NAME: str = os.getenv(
    "CLOUD_MODEL_NAME",
    "gemini-3.5-flash-lite"
)

CLOUD_BASE_URL: str = os.getenv(
    "CLOUD_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)

CLOUD_API_KEY: str = os.getenv(
    "CLOUD_API_KEY",
    ""
)

MODEL_INFO: ModelInfo = ModelInfo(
    vision=True,
    function_calling=True,
    structured_output=True,
    json_output=True,
    family="unknown",
)


def parse_gemma_args_string(raw_args: str) -> Dict[str, Any]:
    """Parse raw Gemma tool argument string into a Python dict."""
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
    """Strips <think>...</think> and <|channel>thought...<channel|> blocks from text."""
    if not text:
        return ""
    # Strip <think>...</think>
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip <|channel>thought...<channel|> or <|channel|>thought...<|channel|>
    cleaned = re.sub(r"<\|?channel\|?>\s*thought.*?<\|?channel\|?>", "", cleaned, flags=re.DOTALL)
    # Strip unclosed thought tags
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<\|?channel\|?>\s*thought.*", "", cleaned, flags=re.DOTALL)
    # Clean up leftover control tags
    cleaned = re.sub(r"</?(?:think|tool_call|tool_response|channel)\|?>?", "", cleaned)
    cleaned = re.sub(r"<\|?/?(?:think|tool_call|tool_response|channel)\|?>?", "", cleaned)
    return cleaned.strip()


def extract_gemma_tool_calls(text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Extract leaked Gemma tool call tokens from response text.
    Returns (parsed_tool_calls, cleaned_text).
    """
    if not text:
        return [], text

    tool_calls = []
    clean_text = text

    # Pattern: <|tool_call|>call:Name{...}<|tool_call|> or call:Name{...}
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


class ReasoningStreamParser:
    """
    Parses real-time streaming tokens and categorizes them into
    ('thought', text) or ('content', text) without buffering delays.
    """
    def __init__(self):
        self.in_think = False
        self.in_channel_thought = False
        self.buffer = ""

    def parse(self, chunk: str) -> List[Tuple[str, str]]:
        if not chunk:
            return []

        out: List[Tuple[str, str]] = []
        self.buffer += chunk

        while self.buffer:
            if not self.in_think and not self.in_channel_thought:
                think_idx = self.buffer.find("<think>")
                m = re.search(r"<\|?channel\|?>\s*thought\n?", self.buffer)
                channel_idx = m.start() if m else -1

                indices = [idx for idx in [think_idx, channel_idx] if idx != -1]
                if not indices:
                    partial = re.search(r"<[a-zA-Z|?]*$", self.buffer)
                    if partial:
                        safe_len = partial.start()
                        if safe_len > 0:
                            out.append(("content", self.buffer[:safe_len]))
                            self.buffer = self.buffer[safe_len:]
                        break
                    else:
                        out.append(("content", self.buffer))
                        self.buffer = ""
                        break
                else:
                    first_idx = min(indices)
                    if first_idx > 0:
                        out.append(("content", self.buffer[:first_idx]))

                    if first_idx == think_idx:
                        self.in_think = True
                        self.buffer = self.buffer[think_idx + len("<think>"):]
                    else:
                        self.in_channel_thought = True
                        self.buffer = self.buffer[m.end():]

            elif self.in_think:
                end_idx = self.buffer.find("</think>")
                if end_idx != -1:
                    thought_text = self.buffer[:end_idx]
                    if thought_text:
                        out.append(("thought", thought_text))
                    self.in_think = False
                    self.buffer = self.buffer[end_idx + len("</think>"):]
                else:
                    partial = re.search(r"</[a-zA-Z]*$", self.buffer)
                    if partial:
                        safe_len = partial.start()
                        if safe_len > 0:
                            out.append(("thought", self.buffer[:safe_len]))
                            self.buffer = self.buffer[safe_len:]
                        break
                    else:
                        out.append(("thought", self.buffer))
                        self.buffer = ""
                        break

            elif self.in_channel_thought:
                end_m = re.search(r"<\|?/?channel\|?>\n?", self.buffer)
                if end_m:
                    thought_text = self.buffer[:end_m.start()]
                    if thought_text:
                        out.append(("thought", thought_text))
                    self.in_channel_thought = False
                    self.buffer = self.buffer[end_m.end():]
                else:
                    partial = re.search(r"<[a-zA-Z|?]*$", self.buffer)
                    if partial:
                        safe_len = partial.start()
                        if safe_len > 0:
                            out.append(("thought", self.buffer[:safe_len]))
                            self.buffer = self.buffer[safe_len:]
                        break
                    else:
                        out.append(("thought", self.buffer))
                        self.buffer = ""
                        break

        return out

    def flush(self) -> List[Tuple[str, str]]:
        if self.buffer:
            tag = "thought" if (self.in_think or self.in_channel_thought) else "content"
            res = [(tag, self.buffer)]
            self.buffer = ""
            return res
        return []


class GemmaCompletionClient(OpenAIChatCompletionClient):
    """
    Custom OpenAIChatCompletionClient for Gemma models under llama-server.
    Intercepts create() and create_stream() to yield tagged thoughts and content
    for word-by-word streaming, parse leaked tool tokens, and guarantee valid outputs.
    """

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[Any] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Any = None,
        **kwargs: Any,
    ) -> CreateResult:
        result: CreateResult = await super().create(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
            **kwargs,
        )

        has_tools = bool(tools) and tool_choice != "none"

        if isinstance(result.content, str):
            parsed_calls, clean_text = extract_gemma_tool_calls(result.content)
            if parsed_calls and has_tools:
                func_calls = []
                for i, tc in enumerate(parsed_calls):
                    func_calls.append(
                        FunctionCall(
                            id=f"call_{tc['name']}_{i}",
                            name=tc["name"],
                            arguments=json.dumps(tc["arguments"]),
                        )
                    )
                return CreateResult(
                    finish_reason="function_calls",
                    content=func_calls,
                    usage=result.usage,
                    cached=result.cached,
                    thought=result.thought,
                )
            else:
                fallback_text = clean_text if (clean_text and clean_text.strip()) else "Tool operation processed."
                return CreateResult(
                    finish_reason="stop",
                    content=fallback_text,
                    usage=result.usage,
                    cached=result.cached,
                    thought=result.thought,
                )

        return result

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        tool_choice: Any = "auto",
        json_output: Optional[Any] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Any = None,
        **kwargs: Any,
    ):
        has_tools = bool(tools) and tool_choice != "none"
        yielded_str_chunks = False
        final_result: Optional[CreateResult] = None
        parser = ReasoningStreamParser()

        async for chunk in super().create_stream(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
            **kwargs,
        ):
            if isinstance(chunk, str):
                for tag, text in parser.parse(chunk):
                    if text:
                        yielded_str_chunks = True
                        if tag == "thought":
                            yield f"<|atlas_thought|>{text}"
                        else:
                            yield text
            elif isinstance(chunk, CreateResult):
                final_result = chunk
            else:
                yield chunk

        for tag, text in parser.flush():
            if text:
                yielded_str_chunks = True
                if tag == "thought":
                    yield f"<|atlas_thought|>{text}"
                else:
                    yield text

        if not final_result:
            fallback_text = "Tool operation processed."
            if not yielded_str_chunks:
                yield fallback_text
            final_result = CreateResult(
                finish_reason="stop",
                content=fallback_text,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                cached=False,
            )
        elif isinstance(final_result.content, str):
            parsed_calls, clean_text = extract_gemma_tool_calls(final_result.content)
            if parsed_calls and has_tools:
                func_calls = []
                for i, tc in enumerate(parsed_calls):
                    func_calls.append(
                        FunctionCall(
                            id=f"call_{tc['name']}_{i}",
                            name=tc["name"],
                            arguments=json.dumps(tc["arguments"]),
                        )
                    )
                final_result = CreateResult(
                    finish_reason="function_calls",
                    content=func_calls,
                    usage=final_result.usage,
                    cached=final_result.cached,
                    thought=final_result.thought,
                )
            else:
                fallback_text = clean_text if (clean_text and clean_text.strip()) else "Tool operation processed."
                if not yielded_str_chunks:
                    yield fallback_text
                final_result = CreateResult(
                    finish_reason="stop",
                    content=fallback_text,
                    usage=final_result.usage,
                    cached=final_result.cached,
                    thought=final_result.thought,
                )
        elif not final_result.content:
            fallback_text = "Tool operation processed."
            if not yielded_str_chunks:
                yield fallback_text
            final_result = CreateResult(
                finish_reason="stop",
                content=fallback_text,
                usage=final_result.usage,
                cached=final_result.cached,
                thought=final_result.thought,
            )

        yield final_result


# Gemini thought signature patch
THOUGHT_SIGNATURE_CACHE: Dict[str, Any] = {}

_original_to_oai_type = _openai_client.to_oai_type
def _patched_to_oai_type(
    message,
    prepend_name=False,
    model="unknown",
    model_family="unknown",
    include_name_in_message=True,
):
    res = _original_to_oai_type(
        message,
        prepend_name=prepend_name,
        model=model,
        model_family=model_family,
        include_name_in_message=include_name_in_message,
    )

    if isinstance(message, AssistantMessage) and isinstance(message.content, list):
        for msg_dict in res:
            if (
                isinstance(msg_dict, dict)
                and msg_dict.get("role") == "assistant"
                and "tool_calls" in msg_dict
            ):
                for tc in msg_dict["tool_calls"]:
                    if isinstance(tc, dict):
                        cid = tc.get("id")

                        if cid and cid in THOUGHT_SIGNATURE_CACHE:
                            tc["extra_content"] = THOUGHT_SIGNATURE_CACHE[cid]

                        elif "extra_content" not in tc:
                            tc["extra_content"] = {
                                "google": {
                                    "thought_signature": "bypass"
                                }
                            }
    return res


def enable_gemini_patch():
    """
    Enable Gemini thought_signature compatibility patch.
    Call this only when required.
    """
    _openai_client.to_oai_type = _patched_to_oai_type


def disable_gemini_patch():
    """
    Restore AutoGen default behavior.
    """
    _openai_client.to_oai_type = _original_to_oai_type


async def attach_thought_signature_cache(client: OpenAIChatCompletionClient):
    """
    Cache Gemini tool call signatures.
    """
    original_create = client._client.chat.completions.create

    async def wrapped_create(*args, **kwargs):
        response = await original_create(*args, **kwargs)
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message

            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    extra = getattr(tc, "extra_content", None)
                    if extra:
                        THOUGHT_SIGNATURE_CACHE[tc.id] = extra
        return response

    client._client.chat.completions.create = wrapped_create


# Model factories
def get_local_model(
    thinking_budget: int = None
) -> OpenAIChatCompletionClient:
    """
    Factory function for local Gemma client.
    Accepts dynamic thinking budget parameters per request.
    """
    budget = 0 if thinking_budget is None else thinking_budget
    is_thinking_enabled = budget > 0

    extra_body: Dict[str, Any] = {
        "reasoning_budget": budget,
        "thinking_budget": budget,
        "reasoning_budget_tokens": budget,
        "thinking_budget_tokens": budget,
        "chat_template_kwargs": {
            "enable_thinking": is_thinking_enabled
        },
    }

    if not is_thinking_enabled:
        extra_body["reasoning_format"] = "none"

    return GemmaCompletionClient(
        model=LOCAL_MODEL_NAME,
        base_url=LOCAL_BASE_URL,
        api_key="bypass",
        model_info=MODEL_INFO,
        parallel_tool_calls=False,
        extra_body=extra_body,
    )


# thought signatures are by default preserved. pass False for testing.
def get_cloud_model(
    enable_patch: bool = True,
) -> OpenAIChatCompletionClient:

    if enable_patch:
        enable_gemini_patch()

    client = OpenAIChatCompletionClient(
        model=CLOUD_MODEL_NAME,
        base_url=CLOUD_BASE_URL,
        api_key=CLOUD_API_KEY,
        model_info=MODEL_INFO,
        parallel_tool_calls=False,
    )

    if enable_patch:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(attach_thought_signature_cache(client))
        except RuntimeError:
            # No running loop yet — caller must await attach_thought_signature_cache
            # themselves before using the client, or call get_cloud_model() inside
            # an async context.
            pass
    return client
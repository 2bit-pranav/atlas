import os
import re
import json
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

load_dotenv()

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


# class Gemma4CompletionClient(OpenAIChatCompletionClient):
#     """
#     Bi-directional interceptor client for Gemma 4 running under llama-server in AutoGen 0.7.5.
#     """

#     def _sanitize_and_extract(
#         self, text: str, allow_tools: bool = True
#     ) -> Tuple[Optional[str], Optional[List[FunctionCall]], Optional[str]]:
#         if not text:
#             return None, None, None

#         thought_text: Optional[str] = None

#         # 1. Extract Reasoning / Channel thoughts
#         channel_pattern = r"(?:<\|channel\|?>|<channel>)(.*?)(?:<\|/channel\|?>|</channel>|$)"
#         channel_match = re.search(channel_pattern, text, re.DOTALL)
#         if channel_match:
#             thought_text = channel_match.group(1).strip()
#             text = re.sub(channel_pattern, "", text, flags=re.DOTALL).strip()

#         # 2. Strip leaked tool responses
#         text = re.sub(
#             r"(?:<\|tool_response\|?>|<tool_response>).*?(?:<\|/tool_response\|?>|</tool_response>|$)",
#             "",
#             text,
#             flags=re.DOTALL,
#         )

#         # 3. Strip trailing EOG and special control tokens
#         text = re.sub(r"(?:</s>|<\|turn_end\|?>|<\|im_end\|?>)", "", text).strip()

#         function_calls: List[FunctionCall] = []
#         clean_text = text

#         # 4. Extract Tool Calls (matches <|tool_call>, <tool_call>, <tool_call|>, etc.)
#         tool_call_pattern = r"(?:<\|?tool_call\|?>?)?\s*call:([a-zA-Z0-9_]+)\{(.*?)\}\s*(?:<\|?/?tool_call\|?>?)?"
#         matches = list(re.finditer(tool_call_pattern, text, re.DOTALL))

#         if matches:
#             for i, match in enumerate(matches):
#                 full_match_str = match.group(0)
#                 func_name = match.group(1)
#                 raw_args_str = match.group(2).strip()

#                 clean_text = clean_text.replace(full_match_str, "").strip()

#                 if allow_tools:
#                     args_dict = {}

#                     # Clean quote escape artifacts (<|"|> -> ")
#                     cleaned_json_str = raw_args_str.replace('<|"', '"').replace('"|>', '"').replace('<|', '').replace('|>', '')

#                     try:
#                         args_dict = json.loads(f"{{{cleaned_json_str}}}")
#                     except Exception:
#                         # Fallback key-value extraction for non-standard parameter formatting
#                         kv_pattern = r'([a-zA-Z_]\w*)\s*:\s*(?:<\|"\|>|")?(.*?)(?:<\|"\|>|"|\s*$)(?:,|\s*)'
#                         kv_matches = re.findall(kv_pattern, raw_args_str, re.DOTALL)

#                         if kv_matches:
#                             for k, v in kv_matches:
#                                 v_clean = v.strip().replace('<|"', '"').replace('"|>', '"').strip()
#                                 if v_clean.lower() == "true":
#                                     args_dict[k] = True
#                                 elif v_clean.lower() == "false":
#                                     args_dict[k] = False
#                                 else:
#                                     try:
#                                         args_dict[k] = json.loads(v_clean)
#                                     except Exception:
#                                         args_dict[k] = v_clean

#                     function_calls.append(
#                         FunctionCall(
#                             id=f"call_{func_name}_{i}",
#                             name=func_name,
#                             arguments=json.dumps(args_dict),
#                         )
#                     )

#         # Strip any leftover control tags from text output
#         clean_text = re.sub(r"</?(?:tool_call|tool_response|channel)\|?>?", "", clean_text).strip()
#         clean_text = re.sub(r"<\|?/?tool_call\|?>?", "", clean_text).strip()
#         final_content = clean_text if clean_text else None

#         return final_content, function_calls if function_calls else None, thought_text

#     async def create(
#         self,
#         messages: Sequence[LLMMessage],
#         *,
#         tools: Sequence[Any] = [],
#         tool_choice: Any = "auto",
#         json_output: Optional[Any] = None,
#         extra_create_args: Mapping[str, Any] = {},
#         cancellation_token: Any = None,
#         **kwargs: Any,
#     ) -> CreateResult:

#         has_tools = bool(tools)

#         processed_messages = []
#         for msg in messages:
#             if isinstance(msg, AssistantMessage) and isinstance(msg.content, str):
#                 cleaned, _, thought = self._sanitize_and_extract(msg.content, allow_tools=has_tools)
#                 msg = AssistantMessage(
#                     content=cleaned or "Understood.",
#                     source=msg.source,
#                     thought=thought or msg.thought,
#                 )
#             processed_messages.append(msg)

#         result: CreateResult = await super().create(
#             messages=processed_messages,
#             tools=tools,
#             tool_choice=tool_choice,
#             json_output=json_output,
#             extra_create_args=extra_create_args,
#             cancellation_token=cancellation_token,
#             **kwargs,
#         )

#         if isinstance(result.content, str):
#             clean_content, function_calls, extracted_thought = self._sanitize_and_extract(
#                 result.content, allow_tools=has_tools
#             )

#             if function_calls:
#                 return CreateResult(
#                     finish_reason="function_calls",
#                     content=function_calls,
#                     usage=result.usage or RequestUsage(prompt_tokens=0, completion_tokens=0),
#                     cached=result.cached,
#                     thought=extracted_thought,
#                 )
#             else:
#                 fallback_content = clean_content
#                 if not fallback_content:
#                     if extracted_thought:
#                         fallback_content = extracted_thought
#                     else:
#                         fallback_content = "Tool execution completed."

#                 return CreateResult(
#                     finish_reason=result.finish_reason,
#                     content=fallback_content,
#                     usage=result.usage or RequestUsage(prompt_tokens=0, completion_tokens=0),
#                     cached=result.cached,
#                     thought=extracted_thought,
#                 )

#         return result


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
def get_local_model() -> OpenAIChatCompletionClient:
    return OpenAIChatCompletionClient(
        model=LOCAL_MODEL_NAME,
        base_url=LOCAL_BASE_URL,
        api_key="bypass",
        model_info=MODEL_INFO,
        parallel_tool_calls=False,
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
        asyncio.create_task(
            attach_thought_signature_cache(client)
        )
    return client
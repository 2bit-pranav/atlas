"""
Tests per-turn reasoning control by overriding LlamaCppModel by a custom wrapper.

Verdict: A custom LlamaCppModel wrapper class is required because passing 
`chat_template_kwargs` via LlamaCppModel(params={...}) doesn't work: _format_request only
copies whitelisted keys (OpenAI-style + llama.cpp sampler params) into the request, silently dropping
anything else, so the server never got enable_thinking=False and the template defaulted to thinking.
This subclass overrides _format_request and adds the key at the top level of the /v1/chat/completions body.
"""

from strands_harness import create_harness
from strands.models.llamacpp import LlamaCppModel


class PatchedLlamaCpp(LlamaCppModel):
    def __init__(self, *args, enable_thinking: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._enable_thinking = enable_thinking

    def _format_request(self, *args, **kwargs):
        req = super()._format_request(*args, **kwargs)
        req["chat_template_kwargs"] = {"enable_thinking": self._enable_thinking}
        return req


def get_model(use_thinking: bool = False):
    return PatchedLlamaCpp(
        context_window_limit=32768,
        enable_thinking=use_thinking,
        params={
            "cache_prompt": True,
        },
    )


while True:
    print("="*100, end=None)
    user_prompt = input("You: ").strip()

    if not user_prompt:
        continue
    
    if user_prompt.lower() in {"exit", "quit", "q"}:
        print("Exiting...\n" + "="*100)
        break
    
    use_thinking = user_prompt.startswith("think:") or user_prompt.startswith("think ")
    clean_prompt = user_prompt.split(":", 1)[-1].replace("think", "", 1).strip() if use_thinking else user_prompt
    
    model = get_model(use_thinking=use_thinking)
    agent = create_harness(model=model, caching=False, builtin_tools=[], tools=[])

    print(f"\nAgent: ", end="")
    agent(clean_prompt)
    print("\n")
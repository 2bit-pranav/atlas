import os
from typing import Any

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.llm.models import ChatGoogle
from pydantic import BaseModel, Field


class BrowserUseRuntimeResult(BaseModel):
    success: bool = Field(..., description="Whether the browser task completed without an error.")
    final_answer: str = Field(..., description="The synthesized answer produced by browser-use after executing the task.")
    url: str | None = Field(default=None, description="The final URL reached by the browser session.")
    steps: int = Field(default=0, description="Number of browser steps executed.")
    extracted_content: str | None = Field(default=None, description="Any raw extracted content from the browser runtime.")
    error: str | None = Field(default=None, description="Error message if the runtime failed.")


def _get_browser_use_llm() -> ChatGoogle:
    api_key = os.getenv("CLOUD_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "Missing Google API key for browser-use. Set CLOUD_API_KEY or GOOGLE_API_KEY in the environment."
        )

    model_name = os.getenv("CLOUD_MODEL_NAME", "gemini-3.5-flash-lite")
    return ChatGoogle(model=model_name, api_key=api_key)


def _extract_browser_answer(history: Any) -> BrowserUseRuntimeResult:
    final_answer = ""
    extracted_content = None
    last_url = None
    step_count = 0

    if history is not None:
        step_count = len(getattr(history, "history", []) or [])
        for item in reversed(getattr(history, "history", []) or []):
            if getattr(item, "state", None) is not None and getattr(item.state, "current_url", None):
                last_url = item.state.current_url
            for result in reversed(getattr(item, "result", []) or []):
                if getattr(result, "extracted_content", None):
                    extracted_content = result.extracted_content
                    final_answer = str(result.extracted_content)
                    break
            if final_answer:
                break

    if not final_answer:
        last_history_item = (getattr(history, "history", []) or [])[-1] if getattr(history, "history", None) else None
        if last_history_item is not None:
            model_output = getattr(last_history_item, "model_output", None)
            if model_output is not None and getattr(model_output, "final_output", None):
                final_answer = str(model_output.final_output)

    return BrowserUseRuntimeResult(
        success=bool(final_answer or not history),
        final_answer=final_answer or "No browser output was produced.",
        url=last_url,
        steps=step_count,
        extracted_content=extracted_content,
    )


async def run_browser_use_task(
    task: str,
) -> BrowserUseRuntimeResult:
    """Execute a browser-use task and return a structured, assistant-friendly result."""
    if not task or not task.strip():
        return BrowserUseRuntimeResult(
            success=False,
            final_answer="No task provided.",
            error="The browser-use tool requires a non-empty task string.",
        )

    llm = _get_browser_use_llm()
    browser_profile = BrowserProfile(headless=True)

    max_steps = int(os.getenv("BROWSER_USE_MAX_STEPS", "10"))

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        use_vision=True,
        max_failures=2,
        max_actions_per_step=5,
        enable_planning=True,
        final_response_after_failure=True,
    )

    try:
        history = await agent.run(max_steps=max_steps)
        result = _extract_browser_answer(history)
        return result
    except Exception as exc:  # pragma: no cover - runtime failure is surfaced to the assistant
        return BrowserUseRuntimeResult(
            success=False,
            final_answer="Browser runtime failed.",
            error=str(exc),
        )
    finally:
        try:
            await agent.close()
        except Exception:
            pass

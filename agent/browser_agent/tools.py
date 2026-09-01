import os
import sys
import asyncio
import concurrent.futures
from typing import Any, Callable, Optional
from contextvars import ContextVar

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.llm.models import ChatGoogle, ChatOpenAI
from pydantic import BaseModel, Field

_terminal_callback_var: ContextVar[Optional[Callable[[str], None]]] = ContextVar("_terminal_callback_var", default=None)

def set_terminal_callback(cb: Optional[Callable[[str], None]]) -> None:
    _terminal_callback_var.set(cb)

def log_terminal(message: str) -> None:
    cb = _terminal_callback_var.get()
    if cb:
        try:
            cb(message)
        except Exception:
            pass

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

    model_name = os.getenv("CLOUD_MODEL_NAME", "gemini-3.1-flash-lite")
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

def _on_step_start(state: Any, output: Any, step: int):
    parts = [f"📍 [Step {step}]"]

    current_state = getattr(output, "current_state", None)
    if current_state:
        thought = getattr(current_state, "thought", None)
        next_goal = getattr(current_state, "next_goal", None)
        if next_goal:
            parts.append(f"Goal: {next_goal}")
        elif thought:
            parts.append(f"Thought: {thought[:80]}...")

    actions = getattr(output, "action", []) or []
    action_strs = []
    for act in actions:
        if isinstance(act, dict):
            for k, v in act.items():
                if isinstance(v, dict):
                    params = ", ".join(f"{pk}={pv}" for pk, pv in v.items() if pk not in ("screenshot", "image"))
                    action_strs.append(f"{k}({params})" if params else f"{k}()")
                else:
                    action_strs.append(f"{k}:{v}")
        else:
            action_strs.append(str(act))

    if action_strs:
        parts.append(f"Action: {', '.join(action_strs)}")

    log_line = " | ".join(parts)
    log_terminal(log_line)

def _is_proactor_loop() -> bool:
    if sys.platform != "win32":
        return True
    try:
        loop = asyncio.get_running_loop()
        return hasattr(asyncio, "ProactorEventLoop") and isinstance(loop, asyncio.ProactorEventLoop)
    except Exception:
        return False

async def _run_browser_task_impl(task: str) -> BrowserUseRuntimeResult:
    log_terminal(f"🚀 Launching Browser Task: {task}")

    llm = _get_browser_use_llm()
    browser_profile = BrowserProfile(headless=False)

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
        register_new_step_callback=_on_step_start,
    )

    try:
        history = await agent.run(max_steps=max_steps)
        result = _extract_browser_answer(history)
        log_terminal(f"✅ Browser Task Finished ({result.steps} steps) | Result: {result.final_answer[:120]}")
        return result
    except Exception as exc:
        log_terminal(f"❌ Browser Task Failed: {exc}")
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

    # On Windows, browser subprocess creation requires a ProactorEventLoop.
    # If current loop is SelectorEventLoop, execute in a dedicated Proactor thread.
    if sys.platform == "win32" and not _is_proactor_loop():
        main_loop = asyncio.get_running_loop()
        outer_cb = _terminal_callback_var.get()

        def thread_runner():
            proactor_loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
            asyncio.set_event_loop(proactor_loop)

            def threadsafe_cb(msg: str):
                if outer_cb:
                    main_loop.call_soon_threadsafe(outer_cb, msg)

            set_terminal_callback(threadsafe_cb)
            try:
                return proactor_loop.run_until_complete(_run_browser_task_impl(task))
            finally:
                set_terminal_callback(None)
                try:
                    proactor_loop.close()
                except Exception:
                    pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(thread_runner)
            return await asyncio.wrap_future(future)

    return await _run_browser_task_impl(task)

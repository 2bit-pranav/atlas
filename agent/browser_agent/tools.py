import os
import asyncio
from typing import Any, Callable, Optional
from contextvars import ContextVar
from pydantic import BaseModel, Field

_terminal_callback_var: ContextVar[Optional[Callable[[str], None]]] = ContextVar("_terminal_callback_var", default=None)
_browser_chat_id_var: ContextVar[Optional[str]] = ContextVar("_browser_chat_id_var", default=None)

def set_terminal_callback(cb: Optional[Callable[[str], None]]) -> None:
    _terminal_callback_var.set(cb)

def log_terminal(message: str) -> None:
    cb = _terminal_callback_var.get()
    if cb:
        try:
            cb(message)
        except Exception:
            pass

def set_browser_chat_id(chat_id: Optional[str]) -> None:
    _browser_chat_id_var.set(chat_id)

class BrowserUseRuntimeResult(BaseModel):
    success: bool = Field(..., description="Whether the browser task completed without an error.")
    final_answer: str = Field(..., description="The synthesized answer produced by browser-use after executing the task.")
    url: str | None = Field(default=None, description="The final URL reached by the browser session.")
    steps: int = Field(default=0, description="Number of browser steps executed.")
    extracted_content: str | None = Field(default=None, description="Any raw extracted content from the browser runtime.")
    error: str | None = Field(default=None, description="Error message if the runtime failed.")

def _get_browser_use_llm(use_local: bool = False):
    if use_local:
        from browser_use.llm.models import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf"),
            base_url=os.getenv("LOCAL_BASE_URL", "http://127.0.0.1:8000/v1")
        )

    from browser_use.llm.models import ChatGoogle
    api_key = os.getenv("CLOUD_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "Missing Google API key for browser-use. Set CLOUD_API_KEY or GOOGLE_API_KEY in the environment."
        )
    
    model_name = os.getenv("CLOUD_MODEL_NAME", "gemini-3.5-flash-lite")
    return ChatGoogle(model=model_name, api_key=api_key)

async def run_browser_use_task(
    task: str,
) -> BrowserUseRuntimeResult:
    """Execute a browser-use task and return a structured, assistant-friendly result."""
    if not task or not task.strip():
        return BrowserUseRuntimeResult(
            success=False,
            final_answer="[BROWSER_ERROR]: No task provided.",
            error="The browser-use tool requires a non-empty task string.",
        )
    
    outer_cb = _terminal_callback_var.get()
    def emit(message: str) -> None:
        if outer_cb:
            try:
                outer_cb(message)
            except Exception:
                pass

    try:
        llm = _get_browser_use_llm(use_local=False)
        from browser_use import Agent
        emit(f"Executing browser task: {task[:80]}...")
        agent = Agent(task=task, llm=llm)
        history = await agent.run()
        final_answer = history.final_result() or "Browser task executed."
        steps_count = len(history.history) if hasattr(history, "history") and history.history else 1
        emit(f"Browser task finished in {steps_count} steps.")
        return BrowserUseRuntimeResult(
            success=True,
            final_answer=final_answer,
            steps=steps_count,
        )
    except (TimeoutError, ConnectionError) as e:
        return BrowserUseRuntimeResult(
            success=False,
            final_answer=f"[NETWORK_ERROR]: Browser connection dropped: {e}",
            error=str(e),
        )
    except Exception as e:
        err_str = str(e).lower()
        if any(k in err_str for k in ["connect", "timeout", "dns", "unreachable", "net::err"]):
            return BrowserUseRuntimeResult(
                success=False,
                final_answer=f"[NETWORK_ERROR]: Connection failed during browser execution: {e}",
                error=str(e),
            )
        return BrowserUseRuntimeResult(
            success=False,
            final_answer=f"[BROWSER_ERROR]: Browser task execution failed: {e}",
            error=str(e),
        )
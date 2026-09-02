import asyncio
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


@dataclass
class BrowserRuntime:
    chat_id: str
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    session: Optional[BrowserSession] = None
    running: bool = False


class BrowserSessionManager:
    """Keeps one external headed browser session per chat."""

    def __init__(self):
        self._runtimes: Dict[str, BrowserRuntime] = {}
        self._lock = threading.Lock()

    def _runtime(self, chat_id: str) -> BrowserRuntime:
        with self._lock:
            runtime = self._runtimes.get(chat_id)
            if runtime:
                return runtime

            ready = threading.Event()
            holder: Dict[str, asyncio.AbstractEventLoop] = {}

            def worker() -> None:
                if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
                    loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
                else:
                    loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                holder["loop"] = loop
                ready.set()
                loop.run_forever()
                loop.close()

            thread = threading.Thread(
                target=worker,
                name=f"atlas-browser-{chat_id}",
                daemon=True,
            )
            thread.start()
            ready.wait()
            runtime = BrowserRuntime(chat_id, holder["loop"], thread)
            self._runtimes[chat_id] = runtime
            return runtime

    @staticmethod
    async def _get_session(runtime: BrowserRuntime) -> BrowserSession:
        if runtime.session is None:
            runtime.session = BrowserSession(
                id=runtime.chat_id,
                browser_profile=BrowserProfile(headless=False, keep_alive=True),
                headless=False,
                keep_alive=True,
            )
        return runtime.session

    async def _run(
        self,
        runtime: BrowserRuntime,
        task: str,
        emit: Callable[[str], None],
    ) -> Dict[str, Any]:
        session = await self._get_session(runtime)
        runtime.running = True

        async def on_step_start(state: Any, output: Any, step: int) -> None:
            current_state = getattr(output, "current_state", None)
            goal = getattr(current_state, "next_goal", None) if current_state else None
            url = await session.get_current_page_url()
            details = f"Goal: {goal}" if goal else f"URL: {url}"
            emit(f"[Step {step}] Running Browser Agent | {details}")

        emit(f"Launching Browser Agent: {task}")
        agent = Agent(
            task=task,
            llm=__import__(
                "agent.browser_agent.tools",
                fromlist=["_get_browser_use_llm"],
            )._get_browser_use_llm(),
            browser_session=session,
            use_vision=False,
            max_failures=2,
            max_actions_per_step=5,
            enable_planning=True,
            final_response_after_failure=True,
            register_new_step_callback=on_step_start,
            keep_alive=True,
            extend_system_message="""
            Your responsibility is to execute the user's requested
            browser workflow accurately and completely.

            GENERAL RULES
            1. Navigate websites and interact with forms using the
            browser.
            2. Prefer completing the workflow over merely describing
            how the user could complete it.
            3. Verify important actions and resulting page state.
            4. Never claim an action succeeded unless the browser
            state provides evidence.

            FORM FILLING
            1. Match fields using labels, surrounding text, and page
            structure.
            2. Never guess unknown user information.
            3. Preserve user-provided values exactly where possible.
            4. Before submitting important forms, verify that required
            fields contain the intended values.

            HUMAN HANDOFF
            When the workflow requires:
            - login credentials
            - OTP / 2FA
            - CAPTCHA
            - payment credentials
            - identity verification
            - security questions
            - any other sensitive user-only input

            DO NOT attempt to bypass or fabricate the information.

            Request human intervention immediately.

            During human intervention:
            - preserve the current browser session
            - do not restart the workflow
            - wait for the human to complete the required action
            - resume from the current page/state afterward

            BOOKING / SUBMISSION
            The user explicitly authorizes the requested booking or
            submission.

            Do not stop merely because the action is consequential.

            Before an irreversible final action:
            1. Verify the target item.
            2. Verify important details.
            3. Verify the final action corresponds to the user's request.
            4. Proceed if the user has explicitly authorized the
            requested transaction.

            After submission:
            - verify the resulting confirmation page/status
            - extract confirmation details
            - report success only after verification.
            """
        )
        try:
            history = await agent.run(max_steps=10)
            final_answer = ""
            for item in reversed(getattr(history, "history", []) or []):
                for result in reversed(getattr(item, "result", []) or []):
                    if getattr(result, "extracted_content", None):
                        final_answer = str(result.extracted_content)
                        break
                if final_answer:
                    break
            emit("Browser Agent finished; browser session remains open.")
            return {
                "success": True,
                "final_answer": final_answer or "Browser task completed without extracted output.",
                "url": await session.get_current_page_url(),
                "steps": len(getattr(history, "history", []) or []),
            }
        except Exception as exc:
            emit(f"Browser Agent failed: {exc}")
            return {"success": False, "final_answer": "Browser runtime failed.", "error": str(exc)}
        finally:
            runtime.running = False
            # Deliberately retain BrowserSession for later chat turns.

    async def run_task(self, chat_id: str, task: str, emit: Callable[[str], None]) -> Dict[str, Any]:
        runtime = self._runtime(chat_id)
        future: Future = asyncio.run_coroutine_threadsafe(
            self._run(runtime, task, emit), runtime.loop
        )
        return await asyncio.wrap_future(future)

    async def close(self, chat_id: str) -> bool:
        runtime = self._runtimes.pop(chat_id, None)
        if not runtime:
            return False
        if runtime.session:
            future = asyncio.run_coroutine_threadsafe(runtime.session.close(), runtime.loop)
            await asyncio.wrap_future(future)
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        return True

    def snapshot(self, chat_id: str) -> Optional[Dict[str, Any]]:
        runtime = self._runtimes.get(chat_id)
        if not runtime:
            return None
        return {
            "chat_id": chat_id,
            "running": runtime.running,
            "persistent": runtime.session is not None,
        }

    def list_sessions(self) -> list[Dict[str, Any]]:
        return [self.snapshot(chat_id) for chat_id in list(self._runtimes)]


browser_session_manager = BrowserSessionManager()

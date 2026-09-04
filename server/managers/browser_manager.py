import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import os
import difflib

from browser_use import Agent, Controller
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from agent.browser_agent.tools import _get_browser_use_llm

STORAGE_DIR = r"C:\Users\prana\Desktop\atlas\server\storage"
USER_DATA_DIR = r"C:\Users\prana\Desktop\atlas\server\data_dir"

@dataclass
class BrowserRuntime:
    chat_id: str
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    session: Optional[BrowserSession] = None
    agent: Optional[Agent] = None
    running: bool = False
    handoff_future: Optional[asyncio.Future] = None
    handoff_prompt: Optional[str] = None
    handoff_id: Optional[str] = None

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
                browser_profile=BrowserProfile(
                    headless=False, 
                    keep_alive=True, 
                    window_size={'width': 1920, 'height': 1080},
                    user_data_dir=USER_DATA_DIR,
                ),
                headless=False,
                keep_alive=True,
            )
        return runtime.session

    async def _run(
        self,
        runtime: BrowserRuntime,
        task: str,
        emit: Callable[[Any], None],
    ) -> Dict[str, Any]:
        session = await self._get_session(runtime)
        runtime.running = True

        async def on_step_start(state: Any, output: Any, step: int) -> None:
            current_state = getattr(output, "current_state", None)
            goal = getattr(current_state, "next_goal", None) if current_state else None
            url = await session.get_current_page_url()
            details = f"Goal: {goal}" if goal else f"URL: {url}"
            emit(f"[Step {step}] Running Browser Agent | {details}")

        # custom tools
        # Use browser_use Controller instance for custom tools
        controller = Controller()

        @controller.action(
            description=(
                "MANDATORY PAUSE ACTION: Use this tool to request missing user information, "
                "phone numbers, missing form choices, passwords, OTP/2FA codes, CAPTCHAs, "
                "or manual human confirmation. You MUST call this whenever a required form field "
                "is missing from the user's initial prompt."
            )
        )
        async def handle_handoff(question: str) -> str:
            if runtime.handoff_future and not runtime.handoff_future.done():
                return await runtime.handoff_future
            if runtime.agent:
                runtime.agent.pause()
            runtime.handoff_id = f"{runtime.chat_id}-handoff-{id(runtime)}"
            runtime.handoff_prompt = question
            runtime.handoff_future = runtime.loop.create_future()
            emit({
                "type": "browser_handoff",
                "chat_id": runtime.chat_id,
                "handoff_id": runtime.handoff_id,
                "question": question,
            })
            response = await runtime.handoff_future
            runtime.handoff_future = None
            runtime.handoff_prompt = None
            runtime.handoff_id = None
            if runtime.agent:
                runtime.agent.resume()
            emit({
                "type": "browser_handoff_resumed",
                "chat_id": runtime.chat_id,
            })
            return response

        @controller.action(
            description=(
                "Finds the full absolute path of a file in local storage using fuzzy matching. "
                "Use this tool whenever you need to upload a file or locate a user document "
                "even if the exact filename is slightly different (e.g. 'resume' vs 'Pranav_Resume.pdf')."
            )
        )
        async def resolve_storage_file(filename_query: str) -> str:
            if not os.path.exists(STORAGE_DIR):
                return f"ERROR: Storage directory {STORAGE_DIR} does not exist."
            
            files = os.listdir(STORAGE_DIR)
            if not files:
                return f"ERROR: Storage directory {STORAGE_DIR} is empty."
            
            # 1. Direct exact or substring match (case-insensitive)
            query_lower = filename_query.lower().strip()
            for f in files:
                if query_lower == f.lower() or query_lower in f.lower() or f.lower().startswith(query_lower):
                    matched_path = os.path.join(STORAGE_DIR, f)
                    return f"MATCH_FOUND: {matched_path}"
                    
            # 2. Fuzzy match fallback
            close_matches = difflib.get_close_matches(filename_query, files, n=1, cutoff=0.3)
            if close_matches:
                matched_path = os.path.join(STORAGE_DIR, close_matches[0])
                return f"MATCH_FOUND: {matched_path}"
                
            return f"FILE_NOT_FOUND: No file matching '{filename_query}' found in {STORAGE_DIR}. Available files: {files}"

        emit(f"Launching Browser Agent: {task}")

        current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")
        llm = _get_browser_use_llm(use_local=False)

        agent = Agent(
            task=task,
            llm=llm,
            browser_session=session,
            controller=controller,
            use_vision=True,
            max_failures=2,
            max_actions_per_step=5,
            enable_planning=True,
            final_response_after_failure=True,
            register_new_step_callback=on_step_start,
            keep_alive=True,
            extend_system_message=f"""
            CURRENT_DATETIME: {current_datetime}

            [CORE DIRECTIVE: AUTONOMOUS EXECUTION WITH MANDATORY HUMAN HANDOFF]
            You are an autonomous browser execution specialist. Your goal is to complete the user's request accurately while adhering strictly to security, data integrity, and privacy boundaries.

            [LOCAL FILE UPLOAD & STORAGE RESOLUTION - MANDATORY EXECUTION ORDER]
            - Storage Directory: `"C:\\Users\\prana\\Desktop\\atlas\\server\\storage"`
            - RULE: File upload fields are NEVER considered "Missing Mandatory Data" on initial inspection.
            - MANDATORY PROTOCOL FOR ANY FILE FIELD / UPLOAD BUTTON:
              When you encounter ANY file upload input, "Add file" button, or document field (e.g., "Photograph", "Resume", "ID"):
              1. DO NOT call `handle_handoff` immediately.
              2. FIRST, call the `resolve_storage_file` tool using the field label as the query (e.g., `resolve_storage_file("photo")` or `resolve_storage_file("resume")`).
              3. IF `MATCH_FOUND` is returned: Proceed to upload or attach that resolved file path.
              4. ONLY IF `resolve_storage_file` returns `FILE_NOT_FOUND`: Call `handle_handoff` to ask the user for the missing file.

            [GOOGLE FORMS & MODAL FILE UPLOAD WORKFLOW]
            When interacting with Google Forms or modal-based file uploaders ("Add file" buttons):
            1. CLICK "Add file" to open the Google Drive Picker modal overlay.
            2. WAIT for the modal/iframe to load.
            3. RESOLVE FILE: Call `resolve_storage_file("<field_name>")` to fetch the path from `C:\\Users\\prana\\Desktop\\repomix\\server\\uploads\\_storage`.
            4. MODAL INTERACTION:
               - Inside the popup/modal, click "Browse" or "Select files from your device" (or upload directly to the active file input inside the modal).
               - Attach the resolved file path.
            5. CONFIRM UPLOAD: Click the blue "Upload" button inside the modal overlay.
            6. VERIFY: Wait for the progress bar to finish and ensure the uploaded file chip appears attached to the main form field before moving to the next question or clicking Submit.
            
            [PRE-INPUT AUDIT ALGORITHM (MUST RUN BEFORE EVERY INPUT OR ACTION)]
            Before typing into ANY field, selecting ANY option, or clicking ANY submit button:
            1. IDENTIFY: Determine if the target field is required (has an asterisk '*', 'required' attribute, or is mandatory for form progression).
            2. VERIFY: Check if the exact value for this field was provided in the user's initial prompt, local storage directory via `resolve_storage_file`, or previous conversation turns.
            3. DECIDE:
            - IF PROVIDED / IN STORAGE: Input the value or file path exactly as resolved.
            - IF MISSING & REQUIRED: STOP IMMEDIATELY. DO NOT FABRICATE DATA. CALL `handle_handoff`.
            - IF MISSING & OPTIONAL: Leave blank or skip to the next required field.

            [ZERO-HALLUCINATION & ANTI-FABRICATION RULES]
            - NEVER invent, guess, or synthesize dummy personal credentials (e.g., phone numbers, passwords, OTPs, CVVs, credit card numbers, addresses, social security/national IDs).
            - NEVER pick random options for required radio buttons, select dropdowns, or checkboxes if the user's preference was not stated.
            - Typing fake data to bypass a form constraint is considered a CRITICAL FAILURE.

            [STRICT HITL TRIGGER CONDITIONS]
            You MUST immediately execute the `handle_handoff` tool when encountering ANY of the following 5 conditions:

            1. MISSING MANDATORY DATA: Any required form text field or detail not specified in the prompt.
               (EXCEPTION: File upload fields MUST attempt `resolve_storage_file` before triggering handoff).
            2. SECURITY & AUTHENTICATION BARRIERS:
            - Login forms requiring user passwords.
            - 2FA / OTP verification codes (SMS, Email, Authenticator App).
            - CAPTCHA / Bot Detection Challenges (Cloudflare, reCAPTCHA, hCaptcha).
            3. FINANCIAL & HIGH-STAKES TRANSACTIONS:
            - Payment gateways requiring Credit Card CVV, Bank PIN, or UPI approval.
            - Final non-reversible booking/purchase buttons unless explicitly authorized with payment details provided.
            4. AMBIGUOUS CHOICE / MULTIPLE MATCHES:
            - When multiple options match the user's criteria equally (e.g., two flights at the same time and price) and the user hasn't specified a tie-breaker.
            5. UNRECOVERABLE NAVIGATION STALLS:
            - When stuck in a loop or an element fails to respond after 2 retry attempts.

            [HANDOFF EXECUTION FORMATTING]
            When invoking `handle_handoff`:
            - Formulate a clear, concise question specifying EXACTLY what information or action is needed from the user.
            - Group multiple missing fields into a single `handle_handoff` call (e.g., "I need your Mobile Number, Date of Birth, and Preferred City to proceed.").
            - Do NOT close or reload the browser page while waiting for the handoff response.
            """,
        )
        runtime.agent = agent
        try:
            history = await agent.run(max_steps=20)
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
            err_msg = str(exc)
            err_lower = err_msg.lower()
            emit(f"Browser Agent failed: {err_msg}")
            
            if any(k in err_lower for k in ["connect", "timeout", "dns", "unreachable", "net::err", "network"]):
                formatted_err = f"[NETWORK_ERROR]: Browser execution failed due to network connectivity issues: {err_msg}"
            elif "api_key" in err_lower or "auth" in err_lower or "401" in err_lower:
                formatted_err = f"[AUTH_ERROR]: Browser LLM authentication failed: {err_msg}"
            else:
                formatted_err = f"[BROWSER_ERROR]: Browser runtime execution failed: {err_msg}"

            return {"success": False, "final_answer": formatted_err, "error": err_msg}
        finally:
            runtime.running = False
            if runtime.handoff_future and not runtime.handoff_future.done():
                runtime.handoff_future.set_exception(RuntimeError("Browser task ended during user handoff"))
            runtime.handoff_future = None
            runtime.handoff_prompt = None
            runtime.handoff_id = None
            runtime.agent = None

    async def run_task(self, chat_id: str, task: str, emit: Callable[[Any], None]) -> Dict[str, Any]:
        runtime = self._runtime(chat_id)
        future = asyncio.run_coroutine_threadsafe(
            self._run(runtime, task, emit), runtime.loop
        )
        return await asyncio.wrap_future(future)

    async def close(self, chat_id: str) -> bool:
        runtime = self._runtimes.pop(chat_id, None)
        if not runtime:
            return False
        if runtime.handoff_future and not runtime.handoff_future.done():
            future = runtime.handoff_future
            runtime.handoff_future = None
            runtime.loop.call_soon_threadsafe(future.set_exception, RuntimeError("Browser session closed"))
        if runtime.session:
            future = asyncio.run_coroutine_threadsafe(runtime.session.close(), runtime.loop)
            await asyncio.wrap_future(future)
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        return True

    async def resolve_handoff(self, chat_id: str, response: str) -> bool:
        runtime = self._runtimes.get(chat_id)
        if not runtime or not runtime.handoff_future:
            return False
        future = runtime.handoff_future
        def resolve() -> None:
            if not future.done():
                future.set_result(response)
        runtime.loop.call_soon_threadsafe(resolve)
        return True

    def snapshot(self, chat_id: str) -> Optional[Dict[str, Any]]:
        runtime = self._runtimes.get(chat_id)
        if not runtime:
            return None
        return {
            "chat_id": chat_id,
            "running": runtime.running,
            "persistent": runtime.session is not None,
            "handoff_prompt": runtime.handoff_prompt,
            "handoff_id": runtime.handoff_id,
        }

    def list_sessions(self) -> list[Dict[str, Any]]:
        return [self.snapshot(chat_id) for chat_id in list(self._runtimes)]


browser_session_manager = BrowserSessionManager()
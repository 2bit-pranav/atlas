"""RunExecutor: owns one run from start to terminal event (spec sections 7 and 9).

An asyncio task inside the backend is enough (section 7's "Process model"), and
it survives the frontend dying because nothing here depends on a client.

Per run: build context from the database, build a **fresh** Strands agent (Strands
is stateless per run, section 9), stream it, translate its output into events
and steps, and finish with exactly one terminal event written together with the
run status and the node's task state.

Cancellation follows section 9: mark ``cancelling`` at the API, then here call
``agent.cancel()`` *and* cancel the task, so the in-flight HTTP stream to
llama-server is actually closed rather than left dangling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from typing import Any, Callable

from strands import Agent

from agent.core.repo import Repo, Run
from agent.models import AtlasLlamaCppModel
from agent.run.context import ContextBuilder
from agent.run.events import Broadcaster, EventSink
from agent.run.hooks import RunEvents
from agent.run.mapping import CODE_CANCELLED, RunCancelled, is_cancel, map_exception
from agent.tools.notepad import compact as compact_notepad
from agent.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)

ModelFactory = Callable[[], AtlasLlamaCppModel]

#: How long a run will wait for its own attachments before answering without
#: them. Long enough to cover a slow spreadsheet (measured ~1.06s for 57 KB /
#: 13 sheets), short enough that a stuck worker does not leave the user staring
#: at a spinner. Text files are ready in ~25ms, so this is never reached.
#:
#: Overridable because the right value depends on the machine and on what is
#: being ingested: parsing a spreadsheet on a local SSD wants a second, and the
#: L4c Docling pipeline on a long PDF wants much longer.
SETTLE_TIMEOUT_S = float(os.environ.get("ATLAS_SETTLE_TIMEOUT_S", "8") or 8)


class RunExecutor:
    """Starts runs, and keeps enough state to cancel them."""

    def __init__(
        self,
        repo: Repo,
        broadcaster: Broadcaster,
        model_factory: ModelFactory,
        *,
        context_builder: ContextBuilder | None = None,
        system_prompt: str | None = None,
        tools: list | None = None,
        tool_runtime: ToolRuntime | None = None,
    ) -> None:
        self.repo = repo
        self.broadcaster = broadcaster
        self.model_factory = model_factory
        self.context = context_builder or ContextBuilder(repo)
        self.system_prompt = system_prompt
        # Tools are per-run: the tool *set* is fixed for the whole run so the
        # prompt prefix stays byte-stable and llama's cache survives (spec 10),
        # but each call gets a fresh ToolContext via invocation_state.
        self.tool_runtime = tool_runtime or ToolRuntime(repo)
        self.tools = tools if tools is not None else self.tool_runtime.tools()
        self._tasks: dict[str, asyncio.Task] = {}
        self._agents: dict[str, Agent] = {}
        self._contexts: dict[str, Any] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._state_lock = threading.Lock()
        self._cancelling: set[str] = set()

    # ------------------------------------------------------------- starting --

    def start(self, run: Run) -> None:
        """Spawn the task. Returns immediately; the API replies with run_id."""
        task = asyncio.create_task(self._execute(run), name=f"run-{run.id}")
        self._tasks[run.id] = task

    async def settle(self, run: Run, sink: "EventSink", *, timeout_s: float | None = None) -> list[dict[str, Any]]:
        """Wait, briefly and in the background, for this run's attachments.

        The design constraint is that the *user* must never be the thing that
        waits. A send that arrives while a file is still parsing is a normal
        thing to do -- type a question while a 1 MB log is being chunked -- so
        the message is accepted immediately, the run starts, and only the
        first model token is deferred.

        Measured on this machine (everything local, no network): a 422-byte
        markdown file is ready in 25ms end to end, a 57 KB xlsx with 13 sheets
        in ~1.06s, a 1 MB text file in 364ms. So the normal case returns
        within a few milliseconds of the wait starting, and the timeout only
        ever matters for a genuinely slow parse.

        Returns the attachments still not ``ready`` when the wait expires, so
        the caller can tell the model by name instead of letting it answer as
        if the file did not exist. A ``failed`` parse is terminal and is
        returned immediately -- there is no point waiting for it.
        """
        if timeout_s is None:
            timeout_s = SETTLE_TIMEOUT_S

        ids = tuple(self.repo.attachments_of(run.user_node_id or ""))
        if not ids:
            return []

        deadline = time.monotonic() + timeout_s
        while True:
            states = self.repo.attachment_states(ids)
            waiting = [s for s in states.values() if s["status"] in ("queued", "running")]
            settled = [s for s in states.values() if s["status"] in ("ready", "failed")]
            if not waiting or time.monotonic() >= deadline:
                if waiting:
                    sink.emit(
                        "attachment_pending",
                        {
                            "attachments": [
                                {
                                    "id": s["id"],
                                    "handle": s["handle"],
                                    "name": s["name"],
                                    "status": s["status"],
                                }
                                for s in waiting
                            ],
                            "waited_ms": int(timeout_s * 1000),
                        },
                    )
                    return waiting
                return [s for s in settled if s["status"] == "failed"]

            if self._is_cancelling(run.id):
                return waiting
            # Short poll: the worker flips the row in its own transaction, and
            # a long sleep would make a 25ms text file feel slow.
            await asyncio.sleep(0.02)

    @staticmethod
    def _note_pending(pending: list[dict[str, Any]]) -> str:
        """The sentence the model gets about what it cannot see.

        Written as a user turn because that is what it is: a fact about the
        current moment, not a system instruction. Naming the handle and the
        filename matters -- the model is about to be asked about "the
        spreadsheet" and needs to know which one is missing.
        """
        lines = [
            f"- {p['handle']} ({p['name']}): still being prepared, status '{p['status']}'"
            for p in pending
        ]
        return (
            "Note: the following attachments from this message are not available "
            "yet, so you cannot read them for this turn:\n"
            + "\n".join(lines)
            + "\n\nIf the user's question is about one of these, say plainly that "
            "you cannot see it yet and that you will be able to on the next "
            "message. Do not guess its contents, and do not answer from anything "
            "else as though it were this file."
        )

    async def _execute(self, run: Run) -> None:
        sink = EventSink(self.repo, self.broadcaster, run.id)
        started = time.monotonic()
        agent: Agent | None = None
        hooks: RunEvents | None = None
        usage_total: dict[str, int] = {"inputTokens": 0, "outputTokens": 0}
        phase = "start"

        try:
            sink.emit(
                "run_started",
                {
                    "chat_id": run.chat_id,
                    "user_node_id": run.user_node_id,
                    "assistant_node_id": run.assistant_node_id,
                    "origin": run.origin,
                    "options": run.options or {},
                    "settings_snapshot": run.settings_snapshot or {},
                },
            )

            phase = "settle"
            # The message is already accepted and the event stream is open, so
            # waiting here costs the user nothing -- it only delays the first
            # token by whatever parse time was left. Returns immediately for the
            # common case: a text file is ready in ~25ms, so by the time the
            # user has typed their question it has long since finished.
            pending = await self.settle(run, sink)

            phase = "build_context"
            messages = self.context.build_for_run(run.user_node_id or "")
            if pending:
                # Named explicitly. The alternative -- letting the model answer
                # as though the file did not exist -- is how a user gets a
                # confident, fluent, wrong answer with no signal that anything
                # was missing.
                messages.append(
                    {
                        "role": "user",
                        "content": [{"text": self._note_pending(pending)}],
                    }
                )
            tokens_before = sum(len(str(m.get("content", ""))) // 4 for m in messages)

            phase = "build_agent"
            model = self.model_factory()
            hooks = RunEvents(sink, self.repo, run.assistant_node_id or "")
            agent = Agent(
                model=model,
                messages=messages,
                tools=self.tools,
                hooks=[hooks],
                system_prompt=self.system_prompt,
            )
            self._agents[run.id] = agent

            # One ToolContext per run, handed to every tool through
            # invocation_state rather than instance attributes -- so no tool can
            # hold another run's context even by accident (spec 11.5).
            ctx = self.tool_runtime.context_for(
                run=run,
                chat_id=run.chat_id,
                node_id=run.assistant_node_id or "",
                cancel=self._cancel_event(run.id),
            )
            self._contexts[run.id] = ctx

            if run.options and "thinking" in run.options:
                # Live per-message toggle (section 4); must be explicit because
                # the server defaults thinking ON (L0/S1).
                model.set_thinking(bool(run.options["thinking"]))

            # Replace the placeholder emitted by the invocation hook with real
            # numbers now that the prompt is known.
            phase = "stream"
            flusher = asyncio.create_task(self._flush_loop(sink), name=f"flush-{run.id}")
            try:
                await self._stream(agent, sink, usage_total, run, ctx)
            finally:
                flusher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await flusher
                sink.flush()

            phase = "finalize"
            duration_ms = int((time.monotonic() - started) * 1000)
            sink.flush()
            # The hook provider sees every model call, so it owns the total.
            if hooks is not None:
                usage_total = dict(hooks.usage)

            # The notepad is compacted onto the node (spec 5, section 10): a
            # later turn inherits the plan and the facts, not the whole
            # transcript. Captured before the context is dropped.
            task_state = self._task_state(run, ctx)

            terminal = self.repo.finalize_run(
                run.id,
                status="completed",
                payload={
                    "finish_reason": "end_turn",
                    "usage_total": usage_total,
                    "duration_ms": duration_ms,
                    "tokens_before": tokens_before,
                    "objects": task_state.get("objects", []),
                },
                usage=usage_total,
                task_state=task_state,
            )
            # finalize_run writes inside its own transaction, so the event has
            # to be broadcast separately or clients wait for a keep-alive.
            sink.publish(terminal)

        except asyncio.CancelledError:
            await self._finish_cancelled(run, sink, started, phase)
            raise
        except BaseException as exc:  # noqa: BLE001 - every failure must finalize
            if is_cancel(exc):
                await self._finish_cancelled(run, sink, started, phase)
            else:
                error = map_exception(exc)
                logger.exception("run %s failed in phase %s", run.id, phase)
                sink.flush()
                terminal = self.repo.finalize_run(
                    run.id,
                    status="failed",
                    payload={"error": error, "phase": phase},
                    error=error,
                )
                sink.publish(terminal)
        finally:
            self._tasks.pop(run.id, None)
            self._agents.pop(run.id, None)
            self._contexts.pop(run.id, None)
            self._cancel_events.pop(run.id, None)
            self._cancelling.discard(run.id)

    # ------------------------------------------------------------- run state --

    def _is_cancelling(self, run_id: str) -> bool:
        with self._state_lock:
            return run_id in self._cancelling

    def _cancel_event(self, run_id: str) -> threading.Event:
        """The token tools poll, so a cancel reaches a query mid-flight.

        Strands' own ``cancel_signal`` stops the agent loop, but a blocking
        DuckDB query does not observe that -- this is what section 9 means by
        "tools can be interrupted".
        """
        with self._state_lock:
            event = self._cancel_events.get(run_id)
            if event is None:
                event = threading.Event()
                self._cancel_events[run_id] = event
            return event

    def _task_state(self, run: Run, ctx: Any) -> dict[str, Any]:
        """What the node keeps: the compacted notepad and what it produced."""
        state: dict[str, Any] = {"objects": []}
        try:
            state.update(compact_notepad(ctx))
            state["objects"] = [
                {"id": o.id, "name": o.name, "kind": o.kind}
                for o in ctx.catalog.list(run.chat_id)
                if o.run_id == run.id
            ]
        except Exception:  # noqa: BLE001 - never fail a run over bookkeeping
            logger.exception("could not capture task state for run %s", run.id)
        return state

    async def _stream(
        self,
        agent: Agent,
        sink: EventSink,
        usage_total: dict[str, int],
        run: Run,
        ctx: Any,
    ) -> None:
        """Drive the agent, turning its stream into events."""
        prompt = self._last_user_text(run)

        # ``atlas_ctx`` travels in invocation_state, which Strands hands to every
        # tool that declared a context parameter. That is the whole wiring: the
        # tools read their ToolContext from there and hold no state themselves.
        async for event in agent.stream_async(
            prompt, invocation_state={"atlas_ctx": ctx}
        ):
            if "reasoningText" in event:
                sink.buffer("thinking_delta", event["reasoningText"])
            elif "data" in event and isinstance(event.get("data"), str):
                sink.buffer("text_delta", event["data"])
            elif "messageStopEvent" in event:
                stop = (event.get("messageStopEvent") or {}).get("stopReason")
                if stop and stop != "end_turn":
                    sink.emit(
                        "warning",
                        {
                            "code": "limit_turns" if stop == "max_tokens" else stop,
                            "message": f"model stopped early: {stop}",
                        },
                    )

    def _last_user_text(self, run: Run) -> str:
        """The user text this run must answer.

        The context already ends with that user message; Strands is given the
        text again so it has something to attach the reply to. Later, when the
        ContextBuilder owns prompt assembly, this becomes an empty prompt.
        """
        node = self.repo.get_node(run.user_node_id or "")
        content = node.content if isinstance(node.content, dict) else {}
        texts = [
            str(b.get("text", ""))
            for b in content.get("blocks", []) or []
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n\n".join(t for t in texts if t)

    async def _flush_loop(self, sink: EventSink) -> None:
        """Coalescing window: write buffered deltas about every 50 ms."""
        while True:
            await asyncio.sleep(0.05)
            if sink.due():
                sink.flush()

    async def _finish_cancelled(
        self, run: Run, sink: EventSink, started: float, phase: str
    ) -> None:
        duration_ms = int((time.monotonic() - started) * 1000)
        sink.flush()
        try:
            terminal = self.repo.finalize_run(
                run.id,
                status="cancelled",
                payload={
                    "phase": phase,
                    "partial": True,
                    "duration_ms": duration_ms,
                },
                error={"code": CODE_CANCELLED, "message": "cancelled by the user",
                       "retryable": True},
            )
            sink.publish(terminal)
        except Exception:  # noqa: BLE001
            logger.exception("could not finalize cancelled run %s", run.id)

    # ------------------------------------------------------------ cancelling --

    async def cancel(self, run_id: str) -> None:
        """Section 9: cancel the agent, the tools, *and* the task.

        Three layers, each covering something the others cannot. ``agent.cancel()``
        stops Strands' loop cleanly; setting the run's cancel token is what a
        blocking DuckDB query actually observes, since it never returns to the
        agent loop; and cancelling the asyncio task is what closes the in-flight
        HTTP stream to llama-server, freeing the slot.
        """
        with self._state_lock:
            event = self._cancel_events.get(run_id)
        if event is not None:
            event.set()

        agent = self._agents.get(run_id)
        task = self._tasks.get(run_id)
        if agent is not None:
            with contextlib.suppress(Exception):
                agent.cancel()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def shutdown(self) -> None:
        """Stop everything on backend exit; never leaves a run marked running."""
        for run_id in list(self._tasks):
            await self.cancel(run_id)


__all__ = ["RunExecutor"]

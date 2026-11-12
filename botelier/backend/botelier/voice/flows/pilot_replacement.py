"""Call-owned admission and acknowledged cancellation for explicit host entry.

This does not choose a node, execute a tool or change caller mute strategies.
Native Flows remains the only transition owner. The guard protects native work
before requesting the SDK's normal interruption, then uses ordered supported
frames to acknowledge the actual last consumer rather than an enqueue.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import wraps

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame, ControlFrame, EndFrame, FunctionCallCancelFrame,
    FunctionCallResultFrame, FunctionCallsStartedFrame, InterruptionFrame,
    StopFrame, UninterruptibleFrame,
)


HANDOFF_TIMEOUT_SECONDS = 5.0


@dataclass
class _NodeHandoffBarrier(ControlFrame, UninterruptibleFrame):
    """An ordered, call-owned acknowledgment; no state or speech payload."""


class NodeReplacementGuard:
    """One bounded host replacement, with no background runner or global lock."""

    def __init__(self, *, llm, worker, assistant, is_closed, extra_busy):
        self.worker = worker
        self.assistant = assistant
        self.is_closed = is_closed
        self.extra_busy = extra_busy
        self.closed = False
        self.failed = False
        self.in_progress = False
        self._calls = set()
        self._globals = 0
        self._waiting = None
        self._owner = None

        @llm.event_handler("on_before_push_frame")
        async def starting(processor, frame):
            # This frame hook is synchronous in the SDK, unlike its ordinary
            # function-start notification. It runs BEFORE native runner queueing,
            # so queued work is protected before assistant bookkeeping exists.
            if not self.closed and isinstance(frame, FunctionCallsStartedFrame):
                self._calls.update(
                    (call.function_name, call.tool_call_id) for call in frame.function_calls
                )

        @assistant.event_handler("on_after_process_frame")
        async def completed(processor, frame):
            if isinstance(frame, FunctionCallResultFrame):
                if frame.properties and not frame.properties.is_final:
                    return
            elif not isinstance(frame, FunctionCallCancelFrame):
                return
            self._calls.discard((frame.function_name, frame.tool_call_id))

        @llm.event_handler("on_before_process_frame")
        async def terminating(processor, frame):
            if isinstance(frame, (CancelFrame, EndFrame, StopFrame)):
                # Invalidate before a slow later processor or the final worker
                # event can delay teardown. Never publish output on a late ack.
                self.invalidate()

        @worker.event_handler("on_frame_reached_downstream")
        async def reached(worker, frame):
            waiting = self._waiting
            if waiting is not None and frame is waiting[0] and not waiting[1].done():
                waiting[1].set_result(None)

    def attach(self):
        # FlowManager owns the initial worker filter set. Install these AFTER
        # its constructor so native setup cannot silently erase our ack types.
        self.worker.add_reached_downstream_filter((InterruptionFrame, _NodeHandoffBarrier))

    @property
    def blocked(self):
        return self.closed or self.failed or self.in_progress or self.is_closed()

    @property
    def busy(self):
        return bool(
            self._calls or self._globals or self.extra_busy()
            or self.assistant.has_function_calls_in_progress
        )

    def protect(self, schema):
        """Keep the original native signature/options and business owner."""
        handler = schema.handler

        @wraps(handler)
        async def invoke(*args, **kwargs):
            if self.blocked:
                return {"status": "rejected", "reason": "busy_or_stale"}
            # No await before admission. A runner racing with replacement
            # cannot start business I/O between the preflight and interruption.
            self._globals += 1
            try:
                return await handler(*args, **kwargs)
            finally:
                self._globals -= 1

        return replace(schema, handler=invoke)

    def invalidate(self):
        self.closed = True
        self._calls.clear()
        if self._waiting is not None:
            self._waiting[1].cancel()

    async def close(self):
        self.invalidate()
        owner = self._owner
        if owner is not None and owner is not asyncio.current_task():
            await asyncio.gather(owner, return_exceptions=True)

    async def _acknowledge(self, frame):
        future = asyncio.get_running_loop().create_future()
        self._waiting = (frame, future)
        try:
            await self.worker.queue_frame(frame)
            await future
            if self.closed or self.is_closed() or self.worker.has_finished():
                raise RuntimeError("pilot_closed")
        finally:
            self._waiting = None

    async def barrier(self):
        # Use the SAME worker queue as native message/tool updates, not a probe
        # inserted directly into the pipeline that could overtake that queue.
        await self._acknowledge(_NodeHandoffBarrier())

    @asynccontextmanager
    async def replacement(self):
        if self.closed or self.is_closed() or self.worker.has_finished():
            raise RuntimeError("pilot_closed")
        if self.failed:
            raise RuntimeError("pilot_replacement_failed")
        if self.in_progress or self.busy:
            raise RuntimeError("pilot_replacement_busy")
        self.in_progress = True
        self._owner = asyncio.current_task()
        try:
            async with asyncio.timeout(HANDOFF_TIMEOUT_SECONDS):
                await self._acknowledge(InterruptionFrame())
                await self.barrier()
                if self.busy:
                    raise RuntimeError("pilot_replacement_busy")
                yield
        except BaseException as exc:
            # A timeout/caller cancellation is not a successful rollback.
            # Keep tool admission closed until teardown instead of reopening
            # while an unacknowledged interruption may still be in flight.
            self.failed = True
            category = "timeout" if isinstance(exc, TimeoutError) else "handoff"
            logger.warning("native_pilot_replacement_failed category={}", category)
            if isinstance(exc, asyncio.CancelledError) and self.closed:
                raise RuntimeError("pilot_closed") from None
            raise
        finally:
            self.in_progress = False
            self._owner = None

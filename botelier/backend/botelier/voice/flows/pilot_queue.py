"""Preserve native node-control frames without protecting interruptible speech.

Pipecat Flows still builds the messages/tools and chooses all transitions.
This call-scoped queue facade forwards to the SAME real PipelineWorker; it
only adds the SDK's supported preservation marker to the two RESET node-entry
frame types emitted by the admitted pilot. It is not a worker or executor.
"""

import asyncio
from collections.abc import AsyncIterable
from dataclasses import dataclass
import inspect

from pipecat.frames.frames import (
    ControlFrame, LLMMessagesUpdateFrame, LLMSetToolsFrame, UninterruptibleFrame,
)
from pipecat.processors.frame_processor import FrameDirection


@dataclass
class _ObservedNodeUpdateBarrier(ControlFrame, UninterruptibleFrame):
    """Text-host-only acknowledgment after a native message/tool update."""


@dataclass
class _NodeMessages(LLMMessagesUpdateFrame, UninterruptibleFrame):
    pass


@dataclass
class _NodeTools(LLMSetToolsFrame, UninterruptibleFrame):
    pass


class InterruptionSafeFlowQueue:
    """Delegate lifecycle/events unchanged; preserve only native node updates."""

    def __init__(self, worker, *, observer=None, observer_timeout=5.0):
        self._worker = worker
        self._observer = observer
        self._observer_timeout = observer_timeout
        self._waiting = {}
        self._closed = False
        if observer is not None:
            @worker.event_handler("on_frame_reached_downstream")
            async def reached(_, frame):
                future = self._waiting.get(id(frame))
                if future is not None and not future.done():
                    future.set_result(None)

            @worker.event_handler("on_pipeline_finished")
            async def finished(_, frame):
                self.close()

    def __getattr__(self, name):
        return getattr(self._worker, name)

    def attach(self):
        """Install the optional marker filter after FlowManager's constructor."""
        if self._observer is not None:
            self._worker.add_reached_downstream_filter(
                (_ObservedNodeUpdateBarrier,),
            )

    def node_speech_started(self, text, *, append_to_context=True):
        if self._observer is not None:
            self._observer.node_speech_started(
                text, append_to_context=append_to_context,
            )

    async def queue_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if type(frame) is LLMMessagesUpdateFrame:
            frame = _NodeMessages(messages=frame.messages, run_llm=frame.run_llm)
        elif type(frame) is LLMSetToolsFrame:
            frame = _NodeTools(tools=frame.tools)
        # Speech, user input and model runs remain normally interruptible.
        await self._worker.queue_frame(frame, direction)

    async def queue_frames(self, frames, direction=FrameDirection.DOWNSTREAM):
        saw_node_update = False
        if isinstance(frames, AsyncIterable):
            async for frame in frames:
                if self._is_node_update(frame, direction):
                    saw_node_update = True
                await self.queue_frame(frame, direction)
        else:
            for frame in frames:
                if self._is_node_update(frame, direction):
                    saw_node_update = True
                await self.queue_frame(frame, direction)
        if saw_node_update and self._observer is not None:
            await self._acknowledge_node_update()

    @staticmethod
    def _is_node_update(frame, direction):
        return (
            direction == FrameDirection.DOWNSTREAM
            and type(frame) in (LLMMessagesUpdateFrame, LLMSetToolsFrame)
        )

    async def _acknowledge_node_update(self):
        if self._closed:
            raise RuntimeError("native_text_closed")
        frame = _ObservedNodeUpdateBarrier()
        future = asyncio.get_running_loop().create_future()
        self._waiting[id(frame)] = future
        self._observer.node_update_started()
        try:
            async with asyncio.timeout(self._observer_timeout):
                await self._worker.queue_frame(frame)
                await future
            result = self._observer.node_update_acknowledged()
            if inspect.isawaitable(result):
                await result
        except BaseException:
            self._observer.node_update_failed()
            raise
        finally:
            self._waiting.pop(id(frame), None)

    def close(self):
        self._closed = True
        for future in self._waiting.values():
            if not future.done():
                future.cancel()

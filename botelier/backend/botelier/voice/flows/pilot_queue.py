"""Preserve native node-control frames without protecting interruptible speech.

Pipecat Flows still builds the messages/tools and chooses all transitions.
This call-scoped queue facade forwards to the SAME real PipelineWorker; it
only adds the SDK's supported preservation marker to the two RESET node-entry
frame types emitted by the admitted pilot. It is not a worker or executor.
"""

from collections.abc import AsyncIterable
from dataclasses import dataclass

from pipecat.frames.frames import (
    LLMMessagesUpdateFrame, LLMSetToolsFrame, UninterruptibleFrame,
)
from pipecat.processors.frame_processor import FrameDirection


@dataclass
class _NodeMessages(LLMMessagesUpdateFrame, UninterruptibleFrame):
    pass


@dataclass
class _NodeTools(LLMSetToolsFrame, UninterruptibleFrame):
    pass


class InterruptionSafeFlowQueue:
    """Delegate lifecycle/events unchanged; preserve only native node updates."""

    def __init__(self, worker):
        self._worker = worker

    def __getattr__(self, name):
        return getattr(self._worker, name)

    async def queue_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if type(frame) is LLMMessagesUpdateFrame:
            frame = _NodeMessages(messages=frame.messages, run_llm=frame.run_llm)
        elif type(frame) is LLMSetToolsFrame:
            frame = _NodeTools(tools=frame.tools)
        # Speech, user input and model runs remain normally interruptible.
        await self._worker.queue_frame(frame, direction)

    async def queue_frames(self, frames, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frames, AsyncIterable):
            async for frame in frames:
                await self.queue_frame(frame, direction)
        else:
            for frame in frames:
                await self.queue_frame(frame, direction)

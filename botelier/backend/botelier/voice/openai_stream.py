"""Preserve speech alongside tools without replacing native OpenAI dispatch."""

from pipecat.frames.frames import LLMFullResponseStartFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.openai.llm import OpenAILLMService


class _TextAndToolStream:
    """Normalize mixed deltas for the pinned SDK's mutually exclusive branches."""

    def __init__(self, stream):
        self._stream = stream

    async def __aiter__(self):
        iterator = self._stream.__aiter__()
        try:
            async for chunk in iterator:
                choice = chunk.choices[0] if chunk.choices else None
                delta = choice.delta if choice else None
                if delta and delta.content and delta.tool_calls:
                    # The native consumer uses `if tool_calls / elif content`.
                    # Emit speech first, then the unmodified tool information.
                    # Only the latter retains usage/finish metadata.
                    yield chunk.model_copy(update={
                        "choices": [choice.model_copy(update={
                            "delta": delta.model_copy(update={"tool_calls": None}),
                            "finish_reason": None,
                        })],
                        "usage": None,
                    })
                    yield chunk.model_copy(update={
                        "choices": [choice.model_copy(update={
                            "delta": delta.model_copy(update={"content": None}),
                        }), *chunk.choices[1:]],
                    })
                else:
                    yield chunk
        finally:
            close_iterator = getattr(iterator, "aclose", None)
            if close_iterator is not None:
                await close_iterator()

    async def close(self):
        await self._stream.close()


class SpeechPreservingOpenAILLMService(OpenAILLMService):
    def install_context_admission(self, admission):
        """Attach one call-owned policy; ordinary non-pilot calls are unchanged."""
        if getattr(self, "_context_admission", None) is not None:
            raise RuntimeError("llm_context_admission_already_installed")
        self._context_admission = admission

    async def queue_frame(self, frame, direction=FrameDirection.DOWNSTREAM, callback=None):
        admission = getattr(self, "_context_admission", None)
        if admission is not None:
            admission.queued(frame)
        await super().queue_frame(frame, direction, callback)

    async def process_frame(self, frame, direction):
        admission = getattr(self, "_context_admission", None)
        if admission is not None and not admission.allow(frame):
            return
        await super().process_frame(frame, direction)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self.current_response_frame_id = frame.id
                self.current_response_text = ""
            elif isinstance(frame, TextFrame):
                self.current_response_text = (
                    getattr(self, "current_response_text", "") + frame.text
                )
        await super().push_frame(frame, direction)

    async def get_chat_completions(self, context):
        return _TextAndToolStream(await super().get_chat_completions(context))

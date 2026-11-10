"""Bind terminal actions to the context actually allocated by native TTS.

Creating an empty audio context does not select the UUID that a later
TTSSpeakFrame uses. Bind by frame/response identity, then use the provider's
existing completion/interruption callbacks for that actual context.
"""

import asyncio

from pipecat.frames.frames import LLMFullResponseStartFrame, TTSSpeakFrame


class TerminalSpeechContexts:
    """Cooperative mixin for the application's context-aware TTS services."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._terminal_speech_frames = {}
        self._terminal_response_frames = {}
        self._terminal_binding = None
        self._terminal_response_id = None
        self._terminal_response_context = None
        self._terminal_response_completed = False

    def bind_terminal_speech(self, frame, callback):
        self._terminal_speech_frames[frame.id] = callback

    def bind_terminal_response(self, response_id, callback):
        if response_id == self._terminal_response_id:
            if self._terminal_response_completed:
                asyncio.create_task(callback())
            else:
                self.register_context_done_callback(
                    self._terminal_response_context, callback,
                )
        else:
            self._terminal_response_frames[response_id] = callback

    async def process_frame(self, frame, direction):
        binding = None
        response_id = None
        if isinstance(frame, TTSSpeakFrame):
            binding = self._terminal_speech_frames.pop(frame.id, None)
        elif isinstance(frame, LLMFullResponseStartFrame):
            response_id = frame.id
            binding = self._terminal_response_frames.pop(response_id, None)
        previous = self._terminal_binding
        self._terminal_binding = (binding, response_id)
        try:
            await super().process_frame(frame, direction)
        finally:
            self._terminal_binding = previous

    async def on_turn_context_created(self, context_id):
        callback, response_id = self._terminal_binding or (None, None)
        if response_id is not None:
            self._terminal_response_id = response_id
            self._terminal_response_context = context_id
            self._terminal_response_completed = False
        if callback is not None:
            self.register_context_done_callback(context_id, callback)
        await super().on_turn_context_created(context_id)

    async def on_audio_context_completed(self, context_id):
        if context_id == self._terminal_response_context:
            self._terminal_response_completed = True
        await super().on_audio_context_completed(context_id)

    def _clear_terminal_speech(self):
        self._terminal_speech_frames.clear()
        self._terminal_response_frames.clear()
        self._context_done_callbacks.clear()

    async def stop(self, frame):
        self._clear_terminal_speech()
        await super().stop(frame)

    async def cancel(self, frame):
        self._clear_terminal_speech()
        await super().cancel(frame)

    async def cleanup(self):
        self._clear_terminal_speech()
        await super().cleanup()

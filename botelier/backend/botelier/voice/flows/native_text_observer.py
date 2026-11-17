"""Frame capture and node-update acknowledgements for the native text host."""

from dataclasses import dataclass

from pipecat.frames.frames import (
    ControlFrame,
    DataFrame,
    ErrorFrame,
    FunctionCallResultFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMAssistantPushAggregationFrame,
    TextFrame,
    TTSStartedFrame,
    TTSSpeakFrame,
    UninterruptibleFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class NativeTextTurnBarrier(ControlFrame, UninterruptibleFrame):
    """Last-consumer fence after a text turn reaches a stable native state."""


@dataclass
class _CommitNativeSpeechFrame(DataFrame):
    text: str
    append_to_context: bool = True


class _TextOutputCapture(FrameProcessor):
    def __init__(self, observer):
        super().__init__(name="NativeTextOutputCapture")
        self._text_observer = observer
        self._host = observer.host

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if self._host.closed and isinstance(frame, (
            FunctionCallResultFrame,
            LLMContextFrame,
            LLMFullResponseEndFrame,
            LLMFullResponseStartFrame,
            TextFrame,
            TTSSpeakFrame,
        )):
            return
        if isinstance(frame, TTSSpeakFrame) and direction == FrameDirection.DOWNSTREAM:
            self._host._record_output(frame.text)
            if self._text_observer.defer_node_speech_frame(frame):
                return
            await self._commit_speech(frame.text, frame.append_to_context, direction)
            return
        if isinstance(frame, _CommitNativeSpeechFrame):
            await self._commit_speech(
                frame.text, frame.append_to_context, direction,
            )
            return
        if isinstance(frame, LLMFullResponseStartFrame):
            self._host._model_started()
        elif isinstance(frame, TextFrame):
            self._host._model_text(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._host._model_ended()
        elif isinstance(frame, ErrorFrame):
            self._host._pipeline_error()
        await self.push_frame(frame, direction)

    async def _commit_speech(self, text, append_to_context, direction):
        started = TTSStartedFrame(append_to_context=append_to_context)
        text_frame = TextFrame(text=text)
        text_frame.append_to_context = append_to_context
        await self.push_frame(started, direction)
        await self.push_frame(text_frame, direction)
        await self.push_frame(LLMAssistantPushAggregationFrame(), direction)


class NativeTextObserver:
    """Capture output and acknowledge real node updates; never directs a flow."""

    def __init__(self, host):
        self.host = host
        self.processor = _TextOutputCapture(self)
        self._node_updates = 0
        self._pending_node_speeches = []

    @property
    def node_updates(self):
        return self._node_updates

    def node_update_started(self):
        self._node_updates += 1
        self.host._changed.set()

    def node_speech_started(self, text, *, append_to_context=True):
        if self.host.closed:
            return
        if len(self._pending_node_speeches) >= 16 or not isinstance(text, str):
            self.host._failure = self.host.error_type("initialization")
            self.host._changed.set()
            return
        self._pending_node_speeches.append({
            "text": text,
            "append_to_context": append_to_context,
            "seen": False,
        })

    def defer_node_speech_frame(self, frame):
        if not self._pending_node_speeches:
            return False
        pending = next(
            (item for item in self._pending_node_speeches if not item["seen"]),
            None,
        )
        if pending is None:
            return False
        if (
            pending["text"] != frame.text
            or pending["append_to_context"] != frame.append_to_context
        ):
            return False
        pending["seen"] = True
        return True

    @property
    def has_pending_speech(self):
        return bool(self._pending_node_speeches)

    async def commit_pending_speech(self):
        """Commit each occurrence after the host/SDK's real consumer fence."""
        pending = self._pending_node_speeches
        if pending and not self.host.closed:
            if any(not item["seen"] for item in pending):
                self.host._failure = self.host.error_type("initialization")
                self.host._changed.set()
                return
            for item in pending:
                await self.host._worker.queue_frame(_CommitNativeSpeechFrame(
                    text=item["text"],
                    append_to_context=item["append_to_context"],
                ))
        self._pending_node_speeches = []

    async def node_update_acknowledged(self):
        await self.commit_pending_speech()
        self._node_updates = max(0, self._node_updates - 1)
        self.host._node_update_consumer_acknowledged()

    def node_update_failed(self):
        self.host._node_update_failed()

    def close(self):
        self._pending_node_speeches.clear()
        self._node_updates = 0

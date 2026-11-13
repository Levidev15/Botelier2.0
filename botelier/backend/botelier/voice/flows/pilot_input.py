"""Call-owned context admission during an acknowledged native node handoff.

This is not an executor or an STT mute strategy. Native context/control frames
keep moving; only model inference is deferred. Retain caller message objects,
not whole-context copies or tool invocations, across native RESET.
"""

from pipecat.frames.frames import (
    CancelFrame, EndFrame, InterruptionFrame, LLMContextFrame, StopFrame,
)


MAX_RETAINED_TURNS = 32
MAX_RETAINED_BYTES = 32768
_HELD_NOTIFICATION = "botelier_native_handoff_input"


class HandoffInput:
    """A bounded, task-free policy installed only on an explicit pilot call."""

    def __init__(self, *, llm, user, on_failure):
        install = getattr(llm, "install_context_admission", None)
        if not callable(install):
            raise RuntimeError("pilot_llm_admission_unsupported")
        self.context = user.context
        self.on_failure = on_failure
        self.closed = False
        self.holding = False
        self._marker = object()
        self._queued = set()
        self._seen = set()
        self._users = []
        self._bytes = 0
        self._pending = False
        install(self)

        @user.event_handler("on_before_push_frame")
        def caller_context(processor, frame):
            # This SDK hook runs synchronously after native aggregation writes
            # the message, BEFORE a later RESET can overwrite the shared list.
            if isinstance(frame, LLMContextFrame) and self.holding and not self.closed:
                self._hold(frame)

    def _fail(self, reason):
        self.close()
        self.on_failure(reason)

    def _remember_users(self):
        for message in self.context.get_messages():
            if id(message) in self._seen:
                continue
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            # This pilot admits a text STT -> text LLM pipeline only. Never
            # promote caller data to instructions or serialize unknown objects.
            if not isinstance(content, str):
                self._fail("pilot_input_format")
                return
            remaining = MAX_RETAINED_BYTES - self._bytes
            if (
                len(self._users) >= MAX_RETAINED_TURNS
                or len(content) > remaining
            ):
                self._fail("pilot_input_overflow")
                return
            try:
                size = len(content.encode("utf-8"))
            except UnicodeEncodeError:
                self._fail("pilot_input_format")
                return
            if size > remaining:
                self._fail("pilot_input_overflow")
                return
            self._seen.add(id(message))
            self._users.append(message)
            self._bytes += size

    def _hold(self, frame):
        if frame.context is not self.context:
            self._fail("pilot_input_context")
            return
        self._pending = True
        self._remember_users()
        # Label the notification, not its mutable context. A held notification
        # that arrives late must not request inference AGAIN after release.
        frame.metadata[_HELD_NOTIFICATION] = self._marker

    def queued(self, frame):
        if not isinstance(frame, LLMContextFrame) or self.closed:
            return
        if frame.metadata.get(_HELD_NOTIFICATION) is self._marker:
            return
        if self.holding:
            self._hold(frame)
        else:
            # Track admission before native queueing: an interruption may
            # remove the queued frame before process_frame can observe it.
            self._queued.add(frame.id)
            if len(self._queued) > MAX_RETAINED_TURNS:
                self._fail("pilot_input_overflow")

    def allow(self, frame):
        if isinstance(frame, (CancelFrame, EndFrame, StopFrame)):
            self.close()
        elif isinstance(frame, InterruptionFrame):
            self._queued.clear()
        elif isinstance(frame, LLMContextFrame):
            self._queued.discard(frame.id)
            if self.closed or frame.metadata.get(_HELD_NOTIFICATION) is self._marker:
                return False
            if self.holding:
                self._hold(frame)
                return False
        # In particular, do not pause message/tool updates or readiness frames.
        return True

    def begin(self):
        if self.closed:
            raise RuntimeError("pilot_input_closed")
        self.holding = True
        self._seen = {id(message) for message in self.context.get_messages()}
        self._pending = bool(self._queued)

    def release(self):
        if self.closed:
            raise RuntimeError("pilot_input_closed")
        self._remember_users()
        if self.closed:
            raise RuntimeError("pilot_input_closed")
        present = {id(message) for message in self.context.get_messages()}
        for message in self._users:
            if id(message) not in present:
                self.context.add_message(message)
        pending = self._pending
        self.holding = False
        self._pending = False
        self._users.clear()
        self._seen.clear()
        self._bytes = 0
        return LLMContextFrame(context=self.context) if pending else None

    def close(self):
        # Leave admission CLOSED for late frames; do not detach and accidentally
        # restore inference during teardown. Never log or persist retained text.
        self.closed = True
        self.holding = False
        self._pending = False
        self._queued.clear()
        self._users.clear()
        self._seen.clear()
        self._bytes = 0

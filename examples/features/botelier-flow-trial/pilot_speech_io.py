"""Test-only stream timing; native model parsing, nodes and TTS stay real."""

import asyncio
from dataclasses import replace
import json

import httpx
from pipecat.frames.frames import InterruptionFrame

from node_contract_io import speech
from pilot_io import PilotProviders
from test_pilot_reentry import EntryFence


OLD_PREFIX = "This first part belongs to the previous question. "
OLD_SUFFIX = "This late reply belongs to the previous question."
CURRENT_PROMPT = "Which current fixture should I check?"
CURRENT_REPLY = "I am answering the current fixture question."
CURRENT_INSTRUCTIONS = "Private changed-visit rule: use only the current fixture question."


class DelayedModelText(httpx.AsyncByteStream):
    """A real HTTP streaming body held before its late content, not a fake LLM."""

    def __init__(self, head, tail):
        self.head = head
        self.tail = tail
        self.blocked = asyncio.Event()
        self.gate = asyncio.Event()
        self.tail_yielded = False
        self.cancelled = False
        self.closed = False

    async def __aiter__(self):
        if self.head:
            yield self.head
        self.blocked.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.tail_yielded = True
        yield self.tail

    async def aclose(self):
        self.closed = True


class SpeechProviders(PilotProviders):
    def __init__(self, *, prefix=False):
        super().__init__([OLD_SUFFIX, CURRENT_REPLY])
        self.prefix = prefix
        self.delayed = None

    async def http(self, request):
        response = await super().http(request)
        if (
            response.headers.get("content-type") != "text/event-stream"
            or len([body for body in self.requests if body.get("stream")]) != 1
        ):
            return response
        assert self.delayed is None, "Do not silently retry a held model turn"
        head = b""
        if self.prefix:
            # Preserve the supported actual provider envelope; prepend one
            # complete content event while holding the original later content.
            first = json.loads(response.text.splitlines()[0][6:])
            first["choices"][0]["delta"] = {"role": "assistant", "content": OLD_PREFIX}
            head = ("data: " + json.dumps(first) + "\n\n").encode()
        self.delayed = DelayedModelText(head, response.content)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            stream=self.delayed, request=request,
        )

    def release_blocked_io(self):
        super().release_blocked_io()
        if self.delayed is not None:
            self.delayed.gate.set()


async def queue_changed_visit(call, node_id):
    """Use the guarded application entry, never a raw manager replacement.

    The forbidden-speech assertions are unchanged. The application entry must
    cancel held output itself; releasing the old provider gate cannot be what
    makes replacement complete. The separate raw-manager revision probes keep
    testing defense in depth against an explicitly forced low-level re-entry.
    """
    consumed = asyncio.Event()
    fence = EntryFence()

    @call.created[3].assistant().event_handler("on_after_process_frame")
    async def processed(processor, frame):
        if frame is fence:
            consumed.set()

    slot = getattr(call.compiled, node_id)
    await call.adapter.replace_node(
        replace(slot, instructions=CURRENT_INSTRUCTIONS), CURRENT_PROMPT,
    )
    await call.created[1].queue_frame(fence)
    return consumed


async def interrupt_assistant(call):
    """Characterize native cancellation, not a caller-mute or runtime change."""
    stopped = asyncio.Event()
    interruption = InterruptionFrame()

    @call.created[16].event_handler("on_after_process_frame")
    async def processed(processor, frame):
        if frame is interruption:
            stopped.set()

    await call.created[1].queue_frame(interruption)
    await call.wait_until(stopped.is_set)


async def wait_for_text(call, text):
    """No tool call is required for a plain model-text response."""
    await call.wait_until(lambda: (
        text in "".join(speech(call))
        and not call.created[16].get_audio_contexts()
        and not call.created[5]._bot_speaking
        and not call.created[3].assistant().has_function_calls_in_progress
    ))

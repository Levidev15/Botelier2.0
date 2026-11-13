"""Test-only timing and observation at real STT/model/TTS boundaries."""

import asyncio
from copy import deepcopy
import json
from unittest.mock import patch

import httpx
from pipecat.frames.frames import (
    FunctionCallResultFrame, InterruptionFrame, LLMContextFrame,
)

from pilot_io import PilotProviders
from pilot_speech_io import CURRENT_INSTRUCTIONS, DelayedModelText


class HandoffProviders(PilotProviders):
    """Keep native inference/dispatch; control only external stream bytes."""

    def __init__(self, replies, *, delay_first=False, **kwargs):
        super().__init__(replies, **kwargs)
        self.delay_first = delay_first
        self.delayed = None
        self.call = None
        self.model_seen = asyncio.Event()
        self.model_finished = asyncio.Event()
        self.result_seen = asyncio.Event()
        self.wire = []
        self.issued = []
        self.results = {}

    def state(self):
        adapter = self.call.adapter
        visit = adapter._visit
        return {
            "handoff": adapter._replacement.in_progress,
            "failed": adapter._replacement.failed,
            "node": adapter.manager.current_node,
            "visit": visit.function_name if visit is not None else None,
            "current_guidance": bool(
                adapter._guidance
                and CURRENT_INSTRUCTIONS in adapter._guidance.get("content", "")
            ),
        }

    def observe(self, call):
        self.call = call
        send = self.tts.send

        async def recording_send(payload):
            message = json.loads(payload)
            if message.get("type") == "Speak":
                self.issued.append({"text": message["text"], **self.state()})
            return await send(payload)

        self.tts.send = recording_send

        @call.created[2].event_handler("on_after_process_frame")
        async def model_finished(processor, frame):
            # A correctly deferred notification can be consumed without an
            # HTTP request. Only actual inference counts as model completion.
            if isinstance(frame, LLMContextFrame) and self.wire:
                self.model_finished.set()

        @call.created[2].event_handler("on_before_push_frame")
        async def result_created(processor, frame):
            if not isinstance(frame, FunctionCallResultFrame):
                return
            if frame.properties and not frame.properties.is_final:
                return
            self.results[frame.tool_call_id] = {
                "result": deepcopy(frame.result), **self.state(),
            }
            self.result_seen.set()

    async def http(self, request):
        model = str(request.url) == "https://api.openai.com/v1/chat/completions"
        body = json.loads(request.content) if model else None
        if model and body.get("stream"):
            self.wire.append({"body": body, **self.state()})
            self.model_seen.set()
        response = await super().http(request)
        if (
            self.delay_first and model and body.get("stream")
            and len(self.wire) == 1
        ):
            assert self.delayed is None, "Do not retry the held model response"
            self.delayed = DelayedModelText(b"", response.content)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                stream=self.delayed, request=request,
            )
        return response

    def release_blocked_io(self):
        super().release_blocked_io()
        if self.delayed is not None:
            self.delayed.gate.set()


class ReceiverHold:
    """Hold one actual TTS consumer; never replace cancellation or node entry."""

    def __init__(self, call, phase):
        self.call = call
        self.phase = phase
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.frame = None
        self.barriers = 0
        self.patched = None

    def __enter__(self):
        from botelier.voice.flows.pilot_replacement import _NodeHandoffBarrier

        tts = self.call.created[16]
        process = tts.process_frame

        async def receive(frame, direction):
            if isinstance(frame, _NodeHandoffBarrier):
                self.barriers += 1
            waiting = self.call.adapter._replacement._waiting
            selected = (
                self.phase == "cancel" and isinstance(frame, InterruptionFrame)
                and waiting is not None and frame is waiting[0]
            ) or (
                self.phase == "ready" and isinstance(frame, _NodeHandoffBarrier)
                and self.barriers == 2
            )
            if self.frame is None and selected:
                self.frame = frame
                self.entered.set()
                await self.release.wait()
            return await process(frame, direction)

        self.patched = patch.object(tts, "process_frame", receive)
        self.patched.start()
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.patched.stop()


async def replacement_outcome(task):
    """Observe the real five-second deadline, not a test timeout as success."""
    done, _ = await asyncio.wait({task}, timeout=7)
    assert done, "The real replacement exceeded its own bounded deadline"
    result = (await asyncio.gather(task, return_exceptions=True))[0]
    return None if result is None else {
        "error": type(result).__name__, "message": str(result),
    }


async def observe_while_held(event):
    """A bounded observation window, not a requirement to admit early input.

    The current race produces a native decision immediately. A correct ingress
    gate may instead defer it until readiness; that is also allowed. Never keep
    the ready frame held waiting indefinitely for forbidden early inference.
    """
    waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait({waiter}, timeout=1.0)
        return bool(done)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def wire_guidance(observation):
    return "\n".join(
        str(message.get("content", ""))
        for message in observation["body"]["messages"]
        if message.get("role") in {"system", "developer"}
    )


def wire_tools(observation):
    return {
        tool["function"]["name"]
        for tool in observation["body"].get("tools", [])
        if tool.get("type") == "function"
    }


def user_messages(call):
    """Read the real shared context, without fabricating an input frame."""
    return [
        message["content"] for message in call.created[4].get_messages()
        if isinstance(message, dict) and message.get("role") == "user"
    ]


async def wait_for_user_message(call, text, count=1):
    await call.wait_until(lambda: user_messages(call).count(text) == count)

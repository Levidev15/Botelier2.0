"""Script provider data, never the application's transcript or voice runner."""

import asyncio
import json

import guard
import httpx

from lifecycle_io import Providers


class SpeechThenStall(httpx.AsyncByteStream):
    def __init__(self, prefix):
        self.prefix = prefix
        self.blocked = asyncio.Event()
        self.gate = asyncio.Event()
        self.cancelled = False
        self.closed = False

    async def __aiter__(self):
        yield self.prefix
        self.blocked.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


class TranscriptProviders(Providers):
    def __init__(
        self, replies, *, hold_tts_turn=None, separate_tool_chunks=False,
        stall_after_first=False, usage_on_content=False,
    ):
        super().__init__(hold_tts_turn=hold_tts_turn, model_reply_limit=len(replies))
        self.replies = tuple(replies)
        self.separate_tool_chunks = separate_tool_chunks
        self.stall_after_first = stall_after_first
        self.usage_on_content = usage_on_content
        self.stream = None

    async def http(self, request):
        # Preserve the common destination/method checks and request recording.
        response = await super().http(request)
        body = self.requests[-1]
        if not body.get("stream"):
            return response
        turn = sum(bool(item.get("stream")) for item in self.requests)
        if turn > len(self.replies):
            guard.deny("unexpected_transcript_model_turn")
        reply = self.replies[turn - 1]
        delta = {"role": "assistant"}
        if isinstance(reply, str):
            delta["content"] = reply
            finish_reason = "stop"
        else:
            delta.update(reply)
            finish_reason = "tool_calls"
        base = {
            "id": f"chatcmpl-transcript-{turn}", "created": 1,
            "model": "gpt-4.1-mini", "object": "chat.completion.chunk",
        }
        deltas = [delta]
        if self.separate_tool_chunks and delta.get("content") and delta.get("tool_calls"):
            deltas = [
                {"role": "assistant", "content": delta["content"]},
                {"tool_calls": delta["tool_calls"]},
            ]
        chunks = [
            *[
                {"choices": [{"index": 0, "delta": item, "finish_reason": None}]}
                for item in deltas
            ],
            {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                },
            },
        ]
        if self.usage_on_content:
            chunks[0]["usage"] = chunks.pop()["usage"]
        content = "".join(
            "data: " + json.dumps({**base, **chunk}) + "\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n"
        if self.stall_after_first:
            if self.stream is not None:
                guard.deny("unexpected_stalled_transcript_model_retry")
            self.stream = SpeechThenStall(
                ("data: " + json.dumps({**base, **chunks[0]}) + "\n\n").encode(),
            )
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=self.stream,
            )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=content,
        )

    def release_blocked_io(self):
        # Emergency fixture teardown only; passing disposal keeps this unset.
        if self.stream is not None:
            self.stream.gate.set()

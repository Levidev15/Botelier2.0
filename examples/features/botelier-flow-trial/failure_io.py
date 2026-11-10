"""Failure injection at provider I/O, keeping real service/worker logic active."""

import asyncio
import json

import guard
import httpx

from application_support import RecordingSocket
from lifecycle_io import Providers, SynthesizerSocket


class BlockedStream(httpx.AsyncByteStream):
    """An established HTTP response that never produces its first SSE bytes."""

    def __init__(self, providers, *, timeout=False):
        self.providers = providers
        self.timeout = timeout
        self.closed = False
        self.cancelled = False

    async def __aiter__(self):
        self.providers.fault_seen.set()
        if self.timeout:
            raise httpx.ReadTimeout("offline model stream timed out")
        try:
            await self.providers.release_fault.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        # This only runs during emergency fixture cleanup after a failed test.
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


class RefusedSpeech(SynthesizerSocket):
    """The provider rejects the first model reply, after a normal greeting."""

    def __init__(self, providers):
        super().__init__()
        self.providers = providers

    async def send(self, payload):
        if isinstance(payload, str) and json.loads(payload).get("type") == "Flush":
            if self.flush_count == 1:
                await RecordingSocket.send(self, payload)
                self.flush_count += 1
                self._incoming.put_nowait({
                    "type": "Error", "code": "OFFLINE_REFUSAL",
                    "description": "offline synthesis refused",
                })
                self.providers.fault_seen.set()
                return
        await super().send(payload)


class FailureProviders(Providers):
    """Each fault is explicit, bounded by the real call's termination in tests."""

    FAULTS = {
        "stt_refused_once", "stt_refused", "tts_refused_once", "llm_rejected_once",
        "llm_stream_timeout", "tts_speech_refused", "prewarm_rejected",
        "stt_connect_stall", "stt_confirmation_stall", "tts_connect_stall",
        "llm_headers_stall", "llm_stream_stall", "tts_metadata_stall",
        "prewarm_headers_stall",
    }

    def __init__(self, fault):
        if fault not in self.FAULTS:
            raise ValueError(f"Unknown offline fault: {fault}")
        super().__init__(hold_tts_turn=2 if fault == "tts_metadata_stall" else None)
        self.fault = fault
        self.fault_seen = asyncio.Event()
        self.release_fault = asyncio.Event()
        self.block_cancelled = False
        self.opened_sockets = []
        self.http_stream = None
        self.stt_attempts = 0
        if fault == "stt_confirmation_stall":
            self.stt = RecordingSocket()  # Handshake succeeds, Connected never arrives.
        if fault == "tts_speech_refused":
            self.tts = RefusedSpeech(self)

    async def block(self):
        self.fault_seen.set()
        try:
            await self.release_fault.wait()
        except asyncio.CancelledError:
            self.block_cancelled = True
            raise

    async def connect_stt(self, url, **kwargs):
        if not url.startswith("wss://api.deepgram.com/v2/listen?"):
            guard.deny("unexpected_lifecycle_stt_destination")
        self.stt_attempts += 1
        if self.stt_attempts > 2:
            guard.deny("unexpected_lifecycle_stt_startup_retry")
        if self.fault == "stt_refused":
            await super().connect_stt(url, **kwargs)
            self.fault_seen.set()
            raise ConnectionRefusedError("offline STT connection refused")
        if not self.fault_seen.is_set():
            if self.fault == "stt_refused_once":
                # super() still validates the exact outbound destination.
                await super().connect_stt(url, **kwargs)
                self.fault_seen.set()
                raise ConnectionRefusedError("offline STT connection refused")
            if self.fault == "stt_connect_stall":
                await self.block()
        socket = await super().connect_stt(url, **kwargs)
        self.opened_sockets.append(socket)
        if self.fault == "stt_confirmation_stall":
            self.fault_seen.set()
        return socket

    async def connect_tts(self, url, **kwargs):
        if not url.startswith("wss://api.deepgram.com/v2/speak?"):
            guard.deny("unexpected_lifecycle_tts_destination")
        if not self.fault_seen.is_set():
            if self.fault == "tts_refused_once":
                await super().connect_tts(url, **kwargs)
                self.fault_seen.set()
                raise ConnectionRefusedError("offline TTS connection refused")
            if self.fault == "tts_connect_stall":
                await self.block()
        socket = await super().connect_tts(url, **kwargs)
        self.opened_sockets.append(socket)
        return socket

    async def http(self, request):
        response = await super().http(request)
        streaming = self.requests[-1].get("stream", False)
        prewarm_fault = self.fault.startswith("prewarm_")
        if streaming == prewarm_fault or self.fault_seen.is_set():
            return response
        if self.fault in {"llm_rejected_once", "prewarm_rejected"}:
            self.fault_seen.set()
            return httpx.Response(400, json={
                "error": {
                    "message": "offline model request refused",
                    "type": "invalid_request_error", "param": None,
                    "code": "offline_refusal",
                },
            })
        if self.fault in {"llm_headers_stall", "prewarm_headers_stall"}:
            await self.block()
        if self.fault in {"llm_stream_stall", "llm_stream_timeout"}:
            self.http_stream = BlockedStream(
                self, timeout=self.fault == "llm_stream_timeout",
            )
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                stream=self.http_stream,
            )
        return response

    def release_blocked_io(self):
        """Emergency teardown only; successful stall checks never release gates."""
        self.release_fault.set()

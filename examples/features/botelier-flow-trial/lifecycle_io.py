"""Synthetic external I/O for real-coordinator tests; never a voice runner."""

import asyncio
import base64
from datetime import datetime
import json
from types import SimpleNamespace

import guard
import httpx
from starlette.websockets import WebSocket

from application_support import RecordingSocket


GREETING = "Hello, this is the offline fixture."
QUESTION = "I need the fixture status."
ANSWER = "Your fixture is ready."
CORRECTION = "Actually, check the other fixture."
REVISED_ANSWER = "The other fixture is ready."
PRIVATE_PROMPT = "Private fixture instructions. Never read these aloud."
CALL_SID = "offline-lifecycle-call"
STREAM_SID = "offline-lifecycle-stream"


def assistant_record():
    return SimpleNamespace(
        id="offline-assistant", account_id="offline-account",
        name="Offline fixture", business_name="Fixture business",
        description="", is_active=True, system_prompt=PRIVATE_PROMPT,
        first_message=GREETING, knowledge_base_id=None, tool_set_id=None,
        mcp_connection_id=None, call_settings={}, timezone="UTC",
        stt_provider="deepgram", stt_model="flux-general-en", language="en",
        stt_config={"interrupt_min_words": 2},
        llm_provider="openai", llm_model="gpt-4.1-mini",
        temperature=0.25, max_tokens=231, llm_config={},
        tts_provider="deepgram-flux", tts_voice="flux-heather-en",
        tts_model=None, tts_config={}, allow_interruptions=True,
        vad_enabled=False, vad_provider="silero", vad_config={},
    )


class Records:
    """Only known SQLAlchemy session operations, backed by synthetic records."""

    def __init__(self):
        self.assistant = assistant_record()
        self.call = SimpleNamespace(
            id="offline-call-log", call_sid=CALL_SID,
            started_at=datetime.utcnow(), answered_at=datetime.utcnow(),
            status="in_progress", ai_greeting_completed=False,
            caller_spoke=None,
        )
        self.rows = {
            "Assistant": self.assistant,
            "PhoneNumber": SimpleNamespace(assistant_id="offline-assistant"),
            "CallLog": self.call, "Account": None, "CallEvent": None,
        }
        self.sessions = []
        self.events = []
        self.saved = []

    def session(self):
        session = Session(self)
        self.sessions.append(session)
        return session

    def complete_call(self, logger, **values):
        # The persistence/billing service is a boundary of THIS coordinator
        # checkpoint. Real extraction, buffering and save handoff stay intact.
        self.saved.append(values)
        self.call.status = "completed"
        return True


class Session:
    def __init__(self, records):
        self.records = records
        self.closed = False
        self.model = None

    def query(self, model):
        if self.closed or model.__name__ not in self.records.rows:
            guard.deny("unexpected_lifecycle_query")
        self.model = model.__name__
        return self

    def filter(self, *criteria):
        return self

    def first(self):
        return self.records.rows[self.model]

    def add(self, event):
        if type(event).__name__ != "CallEvent":
            guard.deny("unexpected_lifecycle_write")
        self.records.events.append({
            "event_type": event.event_type, "details": event.details,
        })

    def bulk_insert_mappings(self, model, rows):
        if model.__name__ != "CallEvent":
            guard.deny("unexpected_lifecycle_bulk_write")
        self.records.events.extend(rows)

    def commit(self):
        if self.closed:
            guard.deny("closed_lifecycle_session")

    def rollback(self):
        pass

    def close(self):
        if self.closed:
            raise AssertionError("The coordinator closed a session twice")
        self.closed = True

    def __getattr__(self, name):
        guard.deny("unexpected_lifecycle_persistence_operation")


class Carrier:
    """A real ASGI WebSocket, with an in-memory carrier at its socket boundary."""

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.outgoing = []
        self.stream_task = None
        self.sequence = 0
        self.websocket = WebSocket(
            {"type": "websocket", "path": "/api/ws/call", "headers": []},
            self.incoming.get, self.send,
        )

    async def send(self, message):
        self.outgoing.append(message)
        if message["type"] == "websocket.close" and self.stream_task:
            self.stream_task.cancel()

    def media(self):
        self.sequence += 1
        self.incoming.put_nowait({
            "type": "websocket.receive",
            "text": json.dumps({
                "event": "media", "streamSid": STREAM_SID,
                "sequenceNumber": str(self.sequence),
                "media": {
                    "track": "inbound", "chunk": str(self.sequence),
                    "timestamp": str((self.sequence - 1) * 20),
                    "payload": base64.b64encode(b"\xff" * 160).decode(),
                },
            }),
        })

    def disconnect(self):
        if self.stream_task:
            self.stream_task.cancel()
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    def start_streaming(self):
        # A carrier continues sending 20 ms media packets while mute changes
        # propagate. A single packet can correctly be dropped at that boundary.
        async def stream():
            while True:
                self.media()
                await asyncio.sleep(0.02)
        self.stream_task = asyncio.create_task(stream(), name="offline-carrier-media")

    def wire_messages(self):
        return [
            json.loads(message["text"])
            for message in self.outgoing
            if message["type"] == "websocket.send" and "text" in message
        ]


class SynthesizerSocket(RecordingSocket):
    def __init__(self, hold_turn=None):
        super().__init__()
        self.hold_turn = hold_turn
        self.flush_count = 0
        self.pending_metadata = None

    async def send(self, payload):
        await super().send(payload)
        kind = self.sent[-1].get("type")
        if kind == "Interrupt":
            # A cancelled provider utterance cannot complete a later context.
            self.pending_metadata = None
        elif kind == "Flush":
            # Provider response only: real SDK handles context completion,
            # PCM framing, output timing and BotStoppedSpeakingFrame.
            self.flush_count += 1
            hold = self.flush_count == self.hold_turn
            duration_ms = 2000 if hold else 80
            self._incoming.put_nowait(b"\0" * (duration_ms * 16))
            metadata = {
                "type": "SpeechMetadata", "audio_duration_ms": duration_ms,
            }
            if hold:
                self.pending_metadata = metadata
            else:
                self._incoming.put_nowait(metadata)

    async def complete_speech(self):
        assert self.pending_metadata is not None, "No provider speech is held"
        metadata, self.pending_metadata = self.pending_metadata, None
        await self.deliver(metadata)


class Providers:
    def __init__(self, *, hold_stt=False, hold_tts_turn=None, model_reply_limit=2):
        self.stt = RecordingSocket([{"type": "Connected"}])
        self.tts = SynthesizerSocket(hold_turn=hold_tts_turn)
        self.stt_connected = asyncio.Event()
        self.tts_connected = asyncio.Event()
        self.release_stt = asyncio.Event()
        if not hold_stt:
            self.release_stt.set()
        self.requests = []
        self.model_reply_limit = model_reply_limit

    async def connect_stt(self, url, **kwargs):
        if not url.startswith("wss://api.deepgram.com/v2/listen?"):
            guard.deny("unexpected_lifecycle_stt_destination")
        self.stt_connected.set()
        await self.release_stt.wait()
        return self.stt

    async def connect_tts(self, url, **kwargs):
        if not url.startswith("wss://api.deepgram.com/v2/speak?"):
            guard.deny("unexpected_lifecycle_tts_destination")
        self.tts_connected.set()
        return self.tts

    async def http(self, request):
        if (
            request.method != "POST"
            or str(request.url) != "https://api.openai.com/v1/chat/completions"
        ):
            guard.deny("unexpected_lifecycle_http_destination")
        body = json.loads(request.content)
        self.requests.append(body)
        base = {
            "id": "chatcmpl-offline", "created": 1,
            "model": "gpt-4.1-mini",
        }
        if not body.get("stream"):
            return httpx.Response(200, json={
                **base, "object": "chat.completion",
                "choices": [{
                    "index": 0, "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
        turn = sum(bool(item.get("stream")) for item in self.requests)
        if turn > self.model_reply_limit:
            guard.deny("unexpected_lifecycle_model_retry_or_extra_turn")
        answer = (ANSWER, REVISED_ANSWER)[min(turn - 1, 1)]
        chunks = [
            {"delta": {"role": "assistant", "content": answer}, "finish_reason": None},
            {"delta": {}, "finish_reason": "stop"},
        ]
        content = "".join(
            "data: " + json.dumps({
                **base, "object": "chat.completion.chunk",
                "choices": [{"index": 0, **chunk}],
            }) + "\n\n"
            for chunk in chunks
        )
        content += "data: " + json.dumps({
            **base, "object": "chat.completion.chunk", "choices": [],
            "usage": {
                "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
            },
        }) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=content,
        )

    async def user_event(self, event, text="", turn_index=0):
        await self.stt.deliver({
            "type": "TurnInfo", "turn_index": turn_index, "event": event,
            "transcript": text,
            "audio_window_start": 0.0, "audio_window_end": 1.0,
            "words": [
                {"word": word, "confidence": 0.99} for word in text.split()
            ],
        })

    async def user_turn(self, text=QUESTION, turn_index=0, *, final=True):
        await self.user_event("StartOfTurn", turn_index=turn_index)
        await self.user_event("EndOfTurn" if final else "Update", text, turn_index)

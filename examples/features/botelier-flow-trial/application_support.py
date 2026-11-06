"""Test-only isolation at package boot, database and provider-I/O boundaries.

Voice factories, processors, mapper methods and SDK services are imported from
their real files. No method bodies are extracted, copied or replaced.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import importlib
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

import guard


def load_voice_engine():
    import botelier

    voice_path = Path(botelier.__file__).resolve().parent / "voice"
    if "botelier.voice" not in sys.modules:
        # The real initializer eagerly imports CallHandler and its server/DB
        # dependencies. This checkpoint tests components, not that server boot.
        namespace = types.ModuleType("botelier.voice")
        namespace.__path__ = [str(voice_path)]
        namespace.__package__ = "botelier.voice"
        namespace.__spec__ = ModuleSpec(
            "botelier.voice", loader=None, is_package=True
        )
        sys.modules["botelier.voice"] = namespace
    engine = importlib.import_module("botelier.voice.engine")
    if Path(engine.__file__).resolve() != voice_path / "engine.py":
        raise RuntimeError("Compatibility checks did not load the real engine")
    return engine


def make_config(**overrides):
    load_voice_engine()
    from botelier.voice.agent import VoiceAgentConfig

    fields = {
        "agent_id": "offline-assistant", "account_id": "offline-account",
        "name": "Synthetic compatibility fixture",
        "stt_model": "flux-general-en", "stt_config": {"interrupt_min_words": 2},
        "llm_model": "gpt-4.1-mini", "llm_temperature": 0.25,
        "llm_max_tokens": 231,
        "tts_provider": "deepgram-flux", "tts_voice_id": "flux-heather-en",
        "system_prompt": "Private fixture instructions. Never read these aloud.",
        "enable_vad": False,
    }
    fields.update(overrides)
    return VoiceAgentConfig(**fields)


API_KEYS = {
    "deepgram_api_key": "offline-not-a-credential",
    "openai_api_key": "offline-not-a-credential",
}


def load_function_mapper():
    load_voice_engine()
    if "botelier.database" not in sys.modules:
        # Real ORM declarations, but never an engine, session or connection.
        from sqlalchemy.orm import declarative_base

        database = types.ModuleType("botelier.database")
        database.Base = declarative_base()

        def forbidden_session(*args, **kwargs):
            guard.deny("database_session_requested")

        database.SessionLocal = forbidden_session
        sys.modules["botelier.database"] = database
    # urllib3 probes IPv6 by binding a loopback socket while Twilio imports it.
    # No networking is available in this trial; declare that capability absent
    # rather than permitting bind() or swallowing a guard denial.
    with patch("socket.has_ipv6", False):
        return importlib.import_module("botelier.voice.function_mapper")


@contextmanager
def no_customer_records():
    """Allow only an in-memory empty lookup for terminal tool-usage logging."""
    database = sys.modules["botelier.database"]

    class EmptySession:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return None

        def close(self):
            pass

        def rollback(self):
            pass

        def __getattr__(self, name):
            guard.deny("unexpected_offline_persistence_operation")

    with patch.object(database, "SessionLocal", EmptySession):
        yield


class RecordingSocket:
    """Only provider I/O is replaced; the real service formats all messages."""

    def __init__(self, incoming=()):
        from websockets.protocol import State

        self.state = State.OPEN
        self.response = types.SimpleNamespace(headers={})
        self.sent = []
        self._incoming = asyncio.Queue()
        for message in incoming:
            self._incoming.put_nowait(message)

    async def send(self, payload):
        self.sent.append(json.loads(payload) if isinstance(payload, str) else payload)

    async def close(self):
        from websockets.protocol import State

        self.state = State.CLOSED
        self._incoming.put_nowait(None)

    async def deliver(self, *messages):
        """Wait until the real SDK receive loop has processed these messages."""
        for message in messages:
            await self._incoming.put(message)
        await asyncio.wait_for(self._incoming.join(), timeout=2.0)

    def __aiter__(self):
        async def messages():
            while True:
                message = await self._incoming.get()
                try:
                    if message is None:
                        return
                    yield json.dumps(message) if isinstance(message, dict) else message
                finally:
                    self._incoming.task_done()
        return messages()


@asynccontextmanager
async def started_tts(service):
    """Run real SDK setup/start/context workers with provider I/O already fake."""
    from pipecat.clocks.system_clock import SystemClock
    from pipecat.frames.frames import CancelFrame, StartFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
    from pipecat.utils.asyncio.task_manager import TaskManager

    clock = SystemClock()
    clock.start()
    worker = PipelineWorker(Pipeline([service]))
    manager = TaskManager(loop=asyncio.get_running_loop())
    emitted = []

    async def output(frame, direction=FrameDirection.DOWNSTREAM):
        emitted.append(frame)

    service.push_frame = output
    await service.setup(FrameProcessorSetup(
        clock=clock, task_manager=manager, pipeline_worker=worker,
    ))
    try:
        await service.process_frame(
            StartFrame(audio_out_sample_rate=8000), FrameDirection.DOWNSTREAM
        )
        yield emitted, worker
    finally:
        await service.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        await service.cleanup()


async def eventually(predicate, timeout=2.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), timeout=timeout)

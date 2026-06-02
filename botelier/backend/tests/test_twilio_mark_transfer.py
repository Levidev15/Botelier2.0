import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

_VOICE_DIR = Path(__file__).resolve().parents[1] / "botelier" / "voice"
_voice_pkg = sys.modules.get("botelier.voice")
if _voice_pkg is not None:
    _voice_pkg.__path__ = [str(_VOICE_DIR)]

from botelier.voice.engine import TwilioMarkWatcher
from pipecat.frames.frames import InputTransportMessageFrame, OutputTransportMessageFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.twilio import TwilioFrameSerializer


@pytest.mark.asyncio
async def test_twilio_serializer_deserializes_mark_event():
    serializer = TwilioFrameSerializer(
        stream_sid="MZ123",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )

    frame = await serializer.deserialize(
        '{"event":"mark","streamSid":"MZ123","mark":{"name":"transfer:abc"}}'
    )

    assert isinstance(frame, InputTransportMessageFrame)
    assert frame.message["event"] == "mark"
    assert frame.message["mark"]["name"] == "transfer:abc"


@pytest.mark.asyncio
async def test_twilio_serializer_serializes_mark_message():
    serializer = TwilioFrameSerializer(
        stream_sid="MZ123",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    message = {"event": "mark", "streamSid": "MZ123", "mark": {"name": "transfer:abc"}}

    payload = await serializer.serialize(OutputTransportMessageFrame(message=message))

    assert json.loads(payload) == message


@pytest.mark.asyncio
async def test_twilio_mark_watcher_resolves_matching_mark():
    watcher = TwilioMarkWatcher(stream_sid="MZ123")

    async def acknowledge():
        await asyncio.sleep(0)
        await watcher.process_frame(
            InputTransportMessageFrame(
                message={"event": "mark", "streamSid": "MZ123", "mark": {"name": "transfer:abc"}}
            ),
            FrameDirection.DOWNSTREAM,
        )

    ack_task = asyncio.create_task(acknowledge())
    ok = await watcher.send_mark_and_wait("transfer:abc", timeout=0.2)
    await ack_task

    assert ok is True


@pytest.mark.asyncio
async def test_twilio_mark_watcher_times_out_for_unmatched_mark():
    watcher = TwilioMarkWatcher(stream_sid="MZ123")

    async def acknowledge_wrong_mark():
        await asyncio.sleep(0)
        await watcher.process_frame(
            InputTransportMessageFrame(
                message={"event": "mark", "streamSid": "MZ123", "mark": {"name": "other"}}
            ),
            FrameDirection.DOWNSTREAM,
        )

    ack_task = asyncio.create_task(acknowledge_wrong_mark())
    ok = await watcher.send_mark_and_wait("transfer:abc", timeout=0.01)
    await ack_task

    assert ok is False
    assert watcher._pending == {}


def test_transfer_txml_no_longer_stops_bidirectional_stream():
    source = (
        Path(__file__).resolve().parents[1] / "botelier" / "voice" / "function_mapper.py"
    ).read_text(encoding="utf-8")

    assert "<Stop><Stream" not in source
    assert "WARM_TRANSFER_PSTN_DRAIN_SECS" not in source


def test_flow_transfer_endframe_is_success_gated():
    source = (
        Path(__file__).resolve().parents[1] / "botelier" / "voice" / "function_mapper.py"
    ).read_text(encoding="utf-8")

    assert "End the pipeline — runs regardless of transfer success/failure" not in source
    assert "Flow transfer did not succeed" in source

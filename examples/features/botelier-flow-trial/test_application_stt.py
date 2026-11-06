"""Real factory/subclass + real SDK dispatch; replace only frame delivery."""

import asyncio

import pytest
from pipecat.frames.frames import (
    InterruptionFrame, InterimTranscriptionFrame, TranscriptionFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
)

from application_support import API_KEYS, load_voice_engine, make_config


def exercise(config, messages):
    async def scenario():
        engine = load_voice_engine()
        service = engine.VoiceEngineFactory.create_stt_service(config, API_KEYS)
        emitted = []

        async def broadcast(frame_type, **kwargs):
            emitted.append(frame_type(**kwargs))

        async def push(frame, direction=None):
            emitted.append(frame)

        async def interruption():
            emitted.append(InterruptionFrame())

        # A frame-delivery boundary, not replacement of Botelier's gating or
        # the SDK's event dispatcher/parent handlers.
        service.broadcast_frame = broadcast
        service.push_frame = push
        service.broadcast_interruption = interruption
        snapshots = []
        for event, transcript in messages:
            await service._handle_message({
                "type": "TurnInfo", "event": event, "transcript": transcript,
                "turn_index": 0, "audio_window_start": 0.0,
                "audio_window_end": 1.0,
                "words": [{"word": word, "confidence": 0.99}
                          for word in transcript.split()],
            })
            snapshots.append(list(emitted))
        return emitted, snapshots
    return asyncio.run(scenario())


def test_raw_speech_and_one_word_cannot_clear_audio_before_word_gate():
    _, stages = exercise(make_config(), [
        ("StartOfTurn", ""), ("Update", "please"),
        ("Update", "please wait"), ("Update", "please wait here"),
    ])
    assert [sum(isinstance(f, InterruptionFrame) for f in stage)
            for stage in stages] == [0, 0, 1, 1]
    assert isinstance(stages[0][0], UserStartedSpeakingFrame)


@pytest.mark.parametrize("ending", ["EndOfTurn", "EagerEndOfTurn"])
def test_final_or_eager_words_resolve_gate_once_without_late_clear(ending):
    emitted, stages = exercise(make_config(), [
        ("StartOfTurn", ""), (ending, "please wait"),
        ("EndOfTurn", "please wait"), ("Update", "stale late words"),
    ])
    assert [sum(isinstance(f, InterruptionFrame) for f in stage)
            for stage in stages] == [0, 1, 1, 1]
    assert any(isinstance(f, UserStoppedSpeakingFrame) for f in emitted)


def test_interruptions_disabled_preserves_completed_turn_without_clear():
    emitted, _ = exercise(make_config(enable_interruptions=False), [
        ("StartOfTurn", ""), ("Update", "please wait"),
        ("EndOfTurn", "please wait"),
    ])
    assert not any(isinstance(f, InterruptionFrame) for f in emitted)
    finals = [f for f in emitted if isinstance(f, TranscriptionFrame)]
    assert [(f.text, f.finalized) for f in finals] == [("please wait", True)]
    assert any(isinstance(f, UserStoppedSpeakingFrame) for f in emitted)


def test_eager_transcript_is_not_reported_as_an_accepted_final_turn():
    emitted, stages = exercise(make_config(), [
        ("StartOfTurn", ""), ("EagerEndOfTurn", "maybe Tuesday"),
        ("EndOfTurn", "actually Wednesday"),
    ])
    assert not any(isinstance(f, TranscriptionFrame) for f in stages[1])
    assert any(isinstance(f, InterimTranscriptionFrame) for f in stages[1])
    assert [f.text for f in emitted if isinstance(f, TranscriptionFrame)] == [
        "actually Wednesday"
    ]


def test_new_turn_gets_its_own_word_gate_instead_of_reusing_previous_permission():
    _, stages = exercise(make_config(), [
        ("StartOfTurn", "please wait"), ("EndOfTurn", "please wait"),
        ("StartOfTurn", ""), ("Update", "please"), ("Update", "please stop"),
    ])
    assert [sum(isinstance(f, InterruptionFrame) for f in stage)
            for stage in stages] == [1, 1, 1, 1, 2]


def test_explicit_zero_restores_immediate_interruption():
    emitted, _ = exercise(make_config(stt_config={"interrupt_min_words": 0}), [
        ("StartOfTurn", ""),
    ])
    assert sum(isinstance(f, InterruptionFrame) for f in emitted) == 1


def test_invalid_word_threshold_recovers_without_crashing_or_clearing_on_noise():
    _, stages = exercise(make_config(stt_config={"interrupt_min_words": "invalid"}), [
        ("StartOfTurn", ""), ("Update", "stop"),
    ])
    assert [sum(isinstance(f, InterruptionFrame) for f in stage)
            for stage in stages] == [0, 1]

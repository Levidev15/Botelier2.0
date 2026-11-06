"""Real TTS overrides and SDK transport formatting with a recording socket."""

import asyncio
from unittest.mock import patch

import pytest

from application_support import (
    API_KEYS, RecordingSocket, eventually, load_voice_engine, make_config, started_tts,
)


PROVIDERS = [("deepgram", "aura-2-helena-en"), ("deepgram-flux", "flux-heather-en")]


def make_service(provider, voice, **settings):
    engine = load_voice_engine()
    config = make_config(
        tts_provider=provider, tts_voice_id=voice,
        tts_config={"token_send_min_chars": 0, **settings},
    )
    service = engine.VoiceEngineFactory.create_tts_service(config, API_KEYS)
    service._websocket = RecordingSocket()
    return service


async def speak(service, text, context="utterance-a"):
    frames = [frame async for frame in service.run_tts(text, context)]
    from pipecat.frames.frames import ErrorFrame

    assert not any(isinstance(frame, ErrorFrame) for frame in frames), frames


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_subword_tokens_are_substituted_and_final_tail_precedes_flush(provider, voice):
    async def scenario():
        service = make_service(provider, voice)
        for text in ("wash", "cloth", "s ", "ready"):
            await speak(service, text)
        await service.flush_audio("utterance-a")
        messages = service._websocket.sent
        assert [m["type"] for m in messages] == ["Speak", "Speak", "Flush"]
        assert [m["text"].strip() for m in messages if m["type"] == "Speak"] == [
            "wash cloths", "ready",
        ]
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_operator_substitution_overrides_builtin_without_losing_fragment(provider, voice):
    async def scenario():
        service = make_service(
            provider, voice, word_substitutions={"washcloths": "towels"}
        )
        for text in ("wash", "cloths"):
            await speak(service, text)
        await service.flush_audio("utterance-a")
        assert service._websocket.sent == [
            {"type": "Speak", "text": "towels"}, {"type": "Flush"},
        ]
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_clause_batching_avoids_one_request_per_word_but_flushes_tail(provider, voice):
    async def scenario():
        service = make_service(provider, voice, token_send_min_chars=24)
        for text in ("Please ", "wait ", "while ", "I ", "check. ", "Thanks"):
            await speak(service, text)
        await service.flush_audio("utterance-a")
        spoken = [m["text"].strip() for m in service._websocket.sent if m["type"] == "Speak"]
        assert spoken == ["Please wait while I check.", "Thanks"]
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_interrupt_discards_partial_text_and_its_terminal_callback(provider, voice):
    async def scenario():
        service = make_service(provider, voice, token_send_min_chars=24)
        fired = []

        async def callback():
            fired.append("interrupted-terminal")

        service.register_context_done_callback("utterance-a", callback)
        await speak(service, "stale unfinished")
        await service.on_audio_context_interrupted("utterance-a")
        await speak(service, "Fresh ", context="utterance-b")
        await service.flush_audio("utterance-b")
        await service.on_audio_context_completed("utterance-a")
        await asyncio.sleep(0)
        assert fired == []
        assert [m["text"].strip() for m in service._websocket.sent if m["type"] == "Speak"] == [
            "Fresh"
        ]
        interruption = "Interrupt" if provider == "deepgram-flux" else "Clear"
        assert service._websocket.sent[0] == {"type": interruption}
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_completion_is_context_bound_and_only_fires_once(provider, voice):
    async def scenario():
        service = make_service(provider, voice)
        fired = []

        async def callback():
            fired.append("utterance-a")

        service.register_context_done_callback("utterance-a", callback)
        await service.on_audio_context_completed("unrelated")
        await asyncio.sleep(0)
        assert fired == []
        await service.on_audio_context_completed("utterance-a")
        await service.on_audio_context_completed("utterance-a")
        await asyncio.sleep(0)
        assert fired == ["utterance-a"]
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_sentence_mode_preserves_whole_word_substitution_without_token_buffers(provider, voice):
    async def scenario():
        service = make_service(provider, voice, text_aggregation_mode="sentence")
        await speak(service, "The washcloths are ready.")
        assert service._websocket.sent == [
            {"type": "Speak", "text": "The wash cloths are ready."}
        ]
    asyncio.run(scenario())


def test_native_flux_context_worker_requires_speech_metadata_not_flush_ack():
    async def scenario():
        from pipecat.frames.frames import TTSAudioRawFrame

        service = make_service("deepgram-flux", "flux-heather-en")
        async with started_tts(service) as (emitted, _):
            fired = []

            async def callback():
                fired.append("completed")

            await service.create_audio_context("provider-context")
            service.register_context_done_callback("provider-context", callback)
            await eventually(lambda: service.get_active_audio_context_id() == "provider-context")
            await service._websocket.deliver({"type": "Flushed"})
            await asyncio.sleep(0)
            assert fired == []
            await service._websocket.deliver(
                b"\0" * 320,
                {"type": "SpeechMetadata", "audio_duration_ms": 20},
            )
            await eventually(lambda: fired == ["completed"])
            audio = [f for f in emitted if isinstance(f, TTSAudioRawFrame)]
            assert len(audio) == 1
            assert audio[0].sample_rate == 8000
            assert audio[0].context_id == "provider-context"
    asyncio.run(scenario())


@pytest.mark.parametrize("provider,voice", PROVIDERS)
def test_provider_connect_failure_emits_error_frame_instead_of_crashing(provider, voice):
    async def scenario():
        from pipecat.frames.frames import ErrorFrame

        service = make_service(provider, voice)
        service._websocket = None
        errors, notifications = [], []

        async def output(frame, direction=None):
            errors.append(frame)

        async def unavailable(*args, **kwargs):
            raise OSError("synthetic provider unavailable")

        @service.event_handler("on_connection_error")
        async def connection_error(service, error):
            notifications.append(error)

        service.push_frame = output
        with patch("websockets.asyncio.client.connect", unavailable):
            await service._connect_websocket()
        assert len(errors) == 1 and isinstance(errors[0], ErrorFrame)
        assert "synthetic provider unavailable" in errors[0].error
        await eventually(lambda: bool(notifications))
        assert notifications == ["synthetic provider unavailable"]
        assert service._websocket is None
    asyncio.run(scenario())

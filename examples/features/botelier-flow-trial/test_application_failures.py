"""Actual coordinator/provider failure paths, with no real provider traffic."""

import asyncio

import pytest
from websockets.protocol import State

from failure_io import FailureProviders
from lifecycle_io import (
    ANSWER, CALL_SID, CORRECTION, GREETING, QUESTION, REVISED_ANSWER,
)
from lifecycle_support import OfflineCall


STT_REFUSAL = (
    r"_(?:Gated|Botelier)FluxSTTService#\d+ exception \(.+:\d+\): "
    r"Unknown error occurred: offline STT connection refused"
)


async def ready_for_question(call):
    await call.wait_until(lambda: call.records.call.ai_greeting_completed)
    call.carrier.start_streaming()
    await call.wait_until(
        lambda: any(isinstance(item, bytes) for item in call.providers.stt.sent)
    )


def spoken(call):
    return "".join(
        item["text"] for item in call.providers.tts.sent if item.get("type") == "Speak"
    )


def assert_disposed(call, *, expected_errors=()):
    call.assert_clean(expected_errors=expected_errors)
    assert call.queue.is_stopped and call.queue._task is None
    assert len(call.records.saved) == 1
    assert call.records.saved[0]["call_sid"] == CALL_SID
    assert all(socket.state is State.CLOSED for socket in call.providers.opened_sockets)
    assert all(client.is_closed() for client in call.warmup_clients)


@pytest.mark.parametrize("provider,expected_errors", [
    ("stt", [
        STT_REFUSAL,
    ]),
    ("tts", [
        r"_BotelierDeepgramFluxTTSService#\d+ exception: offline TTS connection refused",
        r"_BotelierDeepgramFluxTTSService#\d+ error: "
        r"_BotelierDeepgramFluxTTSService#\d+ error: offline TTS connection refused",
    ]),
])
def test_transient_connect_refusal_is_reported_and_real_pipeline_recovers(provider, expected_errors):
    """Missing error propagation or a broken reconnect leaves no accepted reply."""
    async def scenario():
        async with OfflineCall(providers=FailureProviders(f"{provider}_refused_once")) as call:
            await call.wait_until(lambda: bool(call.pipeline_errors))
            assert all(not frame.fatal for frame in call.pipeline_errors)
            await ready_for_question(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: any(
                message.get("content") == ANSWER for message in call.created[4].messages
            ))
            await call.finish("caller_hangup")
            assert_disposed(call, expected_errors=expected_errors)
            assert len(call.pipeline_errors) == 1
            assert spoken(call).count(GREETING) == 1
            assert spoken(call).count(ANSWER) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("interruptions", [True, False])
def test_persistent_stt_startup_failure_exits_after_one_retry(interruptions):
    """Do not advertise a running call that has no way to hear its caller."""
    async def scenario():
        providers = FailureProviders("stt_refused")
        async with OfflineCall(providers=providers, interruptions=interruptions) as call:
            await call.wait_until(providers.fault_seen.is_set)
            call.queue = call.handler.call_event_queues[CALL_SID]
            # No caller hangup and no fake runner exit: the genuine fatal frame
            # must stop the native pipeline after the second failed connection.
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5.0)
            assert providers.stt_attempts == 2
            assert len(call.pipeline_errors) == 3
            assert [frame.fatal for frame in call.pipeline_errors] == [False, False, True]
            assert call.pipeline_errors[-1].error == (
                "Speech recognition unavailable after startup retry"
            )
            assert_disposed(call, expected_errors=[
                STT_REFUSAL, STT_REFUSAL,
                r"_(?:Gated|Botelier)FluxSTTService#\d+ error: "
                r"Speech recognition unavailable after startup retry",
                r"A fatal error occurred: ErrorFrame#\d+\(error: "
                r"Speech recognition unavailable after startup retry, fatal: True\)",
            ])
            assert not any(request.get("stream") for request in providers.requests)
            assert not call.records.call.caller_spoke
    asyncio.run(scenario())


@pytest.mark.parametrize("fault,error,expected_errors", [
    ("llm_rejected_once", "Error during completion: Error code: 400", [
        r"SpeechPreservingOpenAILLMService#\d+ exception \(.+:\d+\): "
        r"Error during completion: Error code: 400 - \{'error': "
        r"\{'message': 'offline model request refused', 'type': 'invalid_request_error', "
        r"'param': None, 'code': 'offline_refusal'\}\}",
    ]),
    ("llm_stream_timeout", "LLM completion timeout", [
        r"SpeechPreservingOpenAILLMService#\d+ exception \(.+:\d+\): LLM completion timeout",
    ]),
])
def test_failed_model_turn_is_not_invented_and_next_final_turn_can_recover(fault, error, expected_errors):
    """A failed request must not fabricate an answer or poison the next turn."""
    async def scenario():
        async with OfflineCall(providers=FailureProviders(fault)) as call:
            await ready_for_question(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: bool(call.pipeline_errors))
            assert len(call.pipeline_errors) == 1
            assert call.pipeline_errors[0].error.startswith(error)
            assert not call.pipeline_errors[0].fatal
            assert ANSWER not in spoken(call)
            await call.providers.user_turn(CORRECTION, turn_index=1)
            await call.wait_until(lambda: any(
                message.get("content") == REVISED_ANSWER for message in call.created[4].messages
            ))
            await call.finish("caller_hangup")
            assert_disposed(call, expected_errors=expected_errors)
            assert spoken(call).count(REVISED_ANSWER) == 1
            transcript = call.records.saved[0]["transcript"]
            assert ANSWER not in [item["content"] for item in transcript]
            assert QUESTION in [item["content"] for item in transcript]
            assert CORRECTION in [item["content"] for item in transcript]
            assert call.records.saved[0]["llm_prompt_tokens"] == 11
            assert call.records.saved[0]["llm_completion_tokens"] == 7
            assert len([r for r in call.providers.requests if r.get("stream")]) == 2
            if call.providers.http_stream is not None:
                assert call.providers.http_stream.closed
    asyncio.run(scenario())


def test_provider_rejected_speech_reports_error_and_hangup_disposes_context():
    """A rejected synthesis must remain visible and not leave context tasks alive."""
    async def scenario():
        async with OfflineCall(providers=FailureProviders("tts_speech_refused")) as call:
            await ready_for_question(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: bool(call.pipeline_errors))
            assert len(call.pipeline_errors) == 1
            assert call.pipeline_errors[0].error.endswith(
                "Flux error OFFLINE_REFUSAL: offline synthesis refused"
            )
            await call.finish("caller_hangup")
            assert_disposed(call, expected_errors=[
                r"_BotelierDeepgramFluxTTSService#\d+ Flux error OFFLINE_REFUSAL: "
                r"offline synthesis refused",
                r"_BotelierDeepgramFluxTTSService#\d+ error: "
                r"_BotelierDeepgramFluxTTSService#\d+ Flux error OFFLINE_REFUSAL: "
                r"offline synthesis refused",
            ])
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", [
    "stt_connect_stall", "stt_confirmation_stall", "tts_connect_stall",
    "llm_headers_stall", "llm_stream_stall", "tts_metadata_stall",
    "prewarm_headers_stall",
])
def test_hangup_disposes_stalled_provider_without_releasing_it(fault):
    """Queuing cancel alone is not proof of disposing a blocked real call."""
    async def scenario():
        providers = FailureProviders(fault)
        async with OfflineCall(providers=providers) as call:
            if fault.startswith("llm_") or fault == "tts_metadata_stall":
                await ready_for_question(call)
                await providers.user_turn()
            if fault == "tts_metadata_stall":
                await call.wait_until(lambda: providers.tts.pending_metadata is not None)
            else:
                await call.wait_until(providers.fault_seen.is_set)
            queue = call.handler.call_event_queues[CALL_SID]
            call.queue = queue
            call.carrier.disconnect()
            await call.handler.cancel_call_pipeline(CALL_SID)
            # Native cancellation has a documented 20 s pipeline-drain deadline.
            # Do not shorten it in fixtures or complete the provider protocol.
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=25.0)
            assert not providers.release_fault.is_set()
            assert_disposed(call)
            if fault in {
                "stt_connect_stall", "tts_connect_stall", "llm_headers_stall",
                "prewarm_headers_stall",
            }:
                assert providers.block_cancelled
            if providers.http_stream is not None:
                assert providers.http_stream.cancelled and providers.http_stream.closed
    asyncio.run(scenario())


def test_failed_cache_warmup_does_not_prevent_the_actual_model_turn():
    """Optional cache warmup may fail without aborting or duplicating conversation."""
    async def scenario():
        async with OfflineCall(providers=FailureProviders("prewarm_rejected")) as call:
            await call.wait_until(call.providers.fault_seen.is_set)
            await ready_for_question(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: any(
                message.get("content") == ANSWER for message in call.created[4].messages
            ))
            await call.finish("caller_hangup")
            assert_disposed(call)
            assert spoken(call).count(ANSWER) == 1
            assert call.pipeline_errors == []
            assert sum(
                event["event_type"] == "llm_prewarm_failed"
                for event in call.records.events
            ) == 1
            assert len(call.warmup_clients) == 1
            assert call.warmup_clients[0].is_closed()
    asyncio.run(scenario())


def test_optional_cache_warmup_times_out_without_waiting_for_call_end():
    """A warmup that never responds must not consume a task for the entire call."""
    async def scenario():
        providers = FailureProviders("prewarm_headers_stall")
        async with OfflineCall(providers=providers) as call:
            await call.wait_until(providers.fault_seen.is_set)
            await call.wait_until(lambda: any(
                event["event_type"] == "llm_prewarm_failed"
                for event in call.records.events
            ), timeout=7.0)
            assert providers.block_cancelled
            assert not providers.release_fault.is_set()
            assert call.warmup_clients[0].is_closed()
            assert call.handler.is_pipeline_active(CALL_SID)
            await call.finish("caller_hangup")
            assert_disposed(call)
    asyncio.run(scenario())

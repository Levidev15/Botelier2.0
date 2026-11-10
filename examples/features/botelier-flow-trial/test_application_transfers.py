"""Actual worker -> mapper -> native TTS/playback -> SDK transfer, offline."""

import asyncio
import json
from xml.etree import ElementTree

import pytest

from lifecycle_io import CALL_SID, CORRECTION
from test_application_transcripts import start_conversation, wait_for_reply
from transfer_io import (
    ANNOUNCEMENT, BASE_URL, CALLER_ID, DESTINATION, RESUME_ANSWER, TransferCall,
)


def has_transfer_result(call, status):
    # Native synchronous tools insert this placeholder before their final
    # result replaces it. Poll through that state, not through malformed JSON.
    return any(
        json.loads(message["content"]).get("status") == status
        for message in call.created[4].messages
        if message.get("role") == "tool" and message.get("content") != "IN_PROGRESS"
    )


@pytest.mark.parametrize("mode", ["warm", "cold"])
@pytest.mark.parametrize("source", ["tool", "flow"])
def test_transfer_waits_for_announcement_and_matching_playback_mark(mode, source):
    """Early synthesis/transport events or a wrong mark must not redirect a call."""
    async def scenario():
        async with TransferCall(
            mode=mode, source=source, recording=True, hold_announcement=True,
        ) as call:
            await start_conversation(call)
            await call.wait_until(lambda: CALL_SID in call.handler.call_recording_sids)
            await call.providers.user_turn()
            await call.wait_until(
                lambda: call.providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
            )
            assert call.http.updated.is_set() is False
            assert call.marks() == []
            await call.providers.tts.complete_speech()
            await call.wait_until(lambda: len(call.marks()) == 1)
            assert call.http.updated.is_set() is False
            call.acknowledge("unrelated-fixture-mark")
            await call.wait_until(lambda: call.created[6]._pending)
            assert call.http.updated.is_set() is False
            call.acknowledge(call.marks()[0]["mark"]["name"])
            try:
                await call.wait_until(lambda: not call.created[6]._pending)
                await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            except TimeoutError as error:
                raise AssertionError({
                    "carrier_http": call.http.requests,
                    "timeline": call.records.timeline,
                    "pending_marks": list(call.created[6]._pending),
                    "incoming": call.carrier.incoming.qsize(),
                    "coordinator": [
                        (frame.f_code.co_name, frame.f_lineno)
                        for frame in call.run_task.get_stack()
                    ],
                    "worker_finished": call.created[1].has_finished(),
                    "finished_event": call.finished.is_set(),
                    "errors": call.errors, "tasks": call.remaining_tasks(),
                }) from error

            assert call.http.updated.is_set()
            timeline = call.records.timeline
            assert timeline.index("stop-recording") < timeline.index("update-transfer")
            assert timeline.index("save-transcript") < timeline.index("update-transfer")
            assert timeline.index("transfer-http-result") < timeline.index("record-transfer")
            assert len(call.records.transfers) == 1
            updates = [data["Twiml"][0] for _, data in call.http.requests if "Twiml" in data]
            assert len(updates) == 1
            xml = ElementTree.fromstring(updates[0])
            if mode == "warm":
                dial = xml.find("Dial")
                assert dial.attrib == {"timeout": "30", "callerId": CALLER_ID}
                number = dial.find("Number")
                assert number.text == DESTINATION
                assert number.attrib == {
                    "statusCallback": BASE_URL + "/api/calls/transfer-status",
                    "statusCallbackEvent": "initiated ringing answered completed",
                }
                assert xml.find("Refer") is None
            else:
                assert xml.find("Refer/Sip").text == f"sip:{DESTINATION}@pstn.twilio.com"
                assert xml.find("Dial") is None
            assert xml.find("Stop") is None
            spoken = "".join(
                item.get("text", "") for item in call.providers.tts.sent
                if item.get("type") == "Speak"
            )
            assert spoken.count(ANNOUNCEMENT) == 1
            assert call.records.saved
            assert sum(
                item["content"] == ANNOUNCEMENT
                for item in call.records.saved[-1]["transcript"]
            ) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("status", [400, 404, 500, "timeout"])
@pytest.mark.parametrize("source", ["tool", "flow"])
def test_rejected_transfer_does_not_persist_a_success_or_end_the_worker(status, source):
    """A generic carrier error is not proof of transfer or of an already-ended call."""
    async def scenario():
        async with TransferCall(outcome=status, source=source) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await call.wait_until(lambda: call.http.updated.is_set())
            await call.wait_until(lambda: has_transfer_result(call, "failed"))
            assert call.records.transfers == [], "Rejected transfer was recorded as successful"
            assert call.records.call.has_transfer is False
            assert not call.finished.is_set()
            if source == "flow":
                state = call.mapper._flow_executors["fixture"].state
                assert not state.transfer_requested
            await call.providers.user_turn(CORRECTION, turn_index=1)
            await wait_for_reply(call, RESUME_ANSWER)
            requests = [item for item in call.providers.requests if item.get("stream")]
            assert len(requests) == 2
            pending = set()
            for message in requests[-1]["messages"]:
                for tool in message.get("tool_calls") or []:
                    pending.add(tool["id"])
                if message.get("role") == "tool":
                    assert message["content"] != "IN_PROGRESS"
                    pending.discard(message["tool_call_id"])
            assert not pending, "Resumed model request contained an unfinished transfer tool"
            await call.finish("caller_hangup")
            call.assert_clean(expected_errors=(
                (
                    r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+"
                    if source == "tool" else r"Flow transfer failed: [\s\S]+"
                ),
            ))
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_pending_recording_start_is_resolved_before_transfer_handoff(source):
    """A start racing the announcement must not create an unstopped recording after handoff."""
    async def scenario():
        async with TransferCall(recording=True, hold_start=True, source=source) as call:
            await start_conversation(call)
            await call.wait_until(lambda: call.http.started.is_set())
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            # A bounded observation, not an application timing workaround.
            await asyncio.sleep(0.05)
            assert not call.http.updated.is_set(), "Transfer overtook its pending recording"
            call.http.start_gate.set()
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert call.records.timeline.index("stop-recording") < (
                call.records.timeline.index("update-transfer")
            )
            call.assert_clean()
    asyncio.run(scenario())


def test_recording_start_does_not_outlive_call_coordinator_cleanup():
    """An owned, in-flight recording request must settle before its call is disposed."""
    async def scenario():
        async with TransferCall(recording=True, hold_start=True) as call:
            await start_conversation(call)
            await call.wait_until(lambda: call.http.started.is_set())
            finishing = asyncio.create_task(call.finish("caller_hangup"))
            await asyncio.wait_for(call.finished.wait(), timeout=5)
            try:
                await asyncio.wait_for(asyncio.shield(call.run_task), timeout=0.1)
            except TimeoutError:
                pass
            else:
                raise AssertionError("Coordinator returned with recording HTTP still in flight")
            call.http.start_gate.set()
            await finishing
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_hangup_during_announcement_discards_terminal_callback(source):
    """A completed or late provider event after hangup cannot launch a transfer."""
    async def scenario():
        async with TransferCall(source=source, hold_announcement=True) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(
                lambda: call.providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
            )
            context_ids = list(call.created[-1]._context_done_callbacks)
            assert context_ids
            await call.finish("caller_hangup")
            for context_id in context_ids:
                await call.created[-1].on_audio_context_completed(context_id)
            await asyncio.sleep(0)
            assert not call.http.updated.is_set()
            assert call.records.transfers == []
            assert call.marks() == []
            assert call.created[-1]._terminal_speech_frames == {}
            assert call.created[-1]._terminal_response_frames == {}
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_active_transfer_preserves_existing_function_call_mute_policy(source):
    """Current policy mutes active tools; this check must not invent barge-in semantics."""
    async def scenario():
        async with TransferCall(source=source, hold_announcement=True) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(
                lambda: call.providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
            )
            clears = sum(item.get("event") == "clear" for item in call.carrier.wire_messages())
            assert call.created[3].user()._user_is_muted
            await call.providers.user_turn(CORRECTION, turn_index=1)
            await call.wait_until(
                lambda: call.providers.stt._incoming.empty()
            )
            assert call.providers.tts.pending_metadata is not None
            assert sum(
                item.get("event") == "clear" for item in call.carrier.wire_messages()
            ) == clears
            assert not call.http.updated.is_set()
            assert call.marks() == []
            assert call.records.transfers == []
            await call.providers.tts.complete_speech()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert len([item for item in call.providers.requests if item.get("stream")]) == 1
            assert len(call.records.transfers) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["warm", "cold"])
def test_flow_speaks_configured_announcement_when_model_emits_only_a_tool(mode):
    """An otherwise silent transfer must use its configured node message once."""
    async def scenario():
        async with TransferCall(source="flow", mode=mode, with_preface=False) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            spoken = "".join(
                item.get("text", "") for item in call.providers.tts.sent
                if item.get("type") == "Speak"
            )
            assert spoken.count(ANNOUNCEMENT) == 1
            assert len(call.records.transfers) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_pending_carrier_update_is_off_loop_and_not_prematurely_successful(source):
    """A slow carrier cannot freeze processing or be recorded as already accepted."""
    async def scenario():
        async with TransferCall(source=source, hold_transfer=True) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await call.wait_until(lambda: "update-transfer" in call.records.timeline)
            assert call.records.transfers == []
            assert call.handler.is_pipeline_active(CALL_SID)
            assert not call.created[1].has_finished()
            assert all(timeout == 10 for timeout in call.http.timeouts)
            call.http.transfer_gate.set()
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert len(call.records.transfers) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_inflight_transfer_settles_before_call_cleanup_returns(source):
    """Hangup must observe an already-sent carrier update, not abandon its task."""
    async def scenario():
        async with TransferCall(source=source, hold_transfer=True) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await call.wait_until(lambda: "update-transfer" in call.records.timeline)
            finishing = asyncio.create_task(call.finish("caller_hangup"))
            await asyncio.wait_for(call.finished.wait(), timeout=5)
            try:
                await asyncio.wait_for(asyncio.shield(call.run_task), timeout=0.1)
            except TimeoutError:
                pass
            else:
                raise AssertionError("Coordinator abandoned an in-flight transfer")
            call.http.transfer_gate.set()
            await finishing
            assert len(call.records.transfers) == 1
            assert len([item for item in call.providers.requests if item.get("stream")]) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_recording_stop_failure_preserves_existing_best_effort_handoff_policy(source):
    """A rejected optional recording stop is not falsely reported as stopped."""
    async def scenario():
        async with TransferCall(source=source, recording=True, stop_outcome=500) as call:
            await start_conversation(call)
            await call.wait_until(lambda: CALL_SID in call.handler.call_recording_sids)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert "stop-recording" in call.records.timeline
            assert call.http.updated.is_set()
            assert len(call.records.transfers) == 1
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_hangup_while_waiting_for_mark_cannot_acknowledge_or_start_transfer(source):
    """Teardown releasing a mark waiter is cancellation, not playback approval."""
    async def scenario():
        async with TransferCall(source=source) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            assert not call.http.updated.is_set()
            await call.finish("caller_hangup")
            assert not call.http.updated.is_set(), "Hangup released a stale transfer"
            assert call.records.transfers == []
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_missing_carrier_client_returns_failure_without_closing_the_call(source):
    """Unavailable transfer configuration must not silently strand or end a call."""
    async def scenario():
        async with TransferCall(source=source, credentials=False) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: has_transfer_result(call, "failed"))
            assert call.handler.is_pipeline_active(CALL_SID)
            assert not call.http.updated.is_set()
            assert call.records.transfers == []
            if source == "flow":
                assert not call.mapper._flow_executors["fixture"].state.transfer_requested
            await call.providers.user_turn(CORRECTION, turn_index=1)
            await wait_for_reply(call, RESUME_ANSWER)
            await call.finish("caller_hangup")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_accepted_carrier_update_is_not_retried_or_reported_failed_on_log_write_error(source):
    """A later persistence error cannot undo the already-accepted remote side effect."""
    async def scenario():
        async with TransferCall(source=source) as call:
            call.records.fail_transfer_write = True
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            updates = [url for url, _ in call.http.requests if url.endswith(f"/Calls/{CALL_SID}.json")]
            assert len(updates) == 1
            assert call.records.transfers == []
            assert has_transfer_result(call, "transferred")
            assert not any(
                "couldn't confirm" in item.get("text", "")
                for item in call.providers.tts.sent if item.get("type") == "Speak"
            )
            call.assert_clean(expected_errors=(
                r"Accepted transfer follow-up failed for call offline-lifecycle-call: [\s\S]+"
                if source == "tool" else r"Accepted flow transfer follow-up failed: [\s\S]+",
            ))
    asyncio.run(scenario())

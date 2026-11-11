"""Signed ASGI callbacks connected to the real native voice worker."""

import asyncio

import pytest

from callback_io import BASE_URL, CallbackHarness
from callback_store import ACCOUNT_A, CHILD_A, PHONE_B, TOKEN_B, CallbackStore
from lifecycle_io import CALL_SID
from test_application_transcripts import start_conversation
from test_application_transfer_retries import result_for
from transcript_tools import tool_reply
from transfer_io import TOKEN, TransferCall


def shared_store(call):
    """Both actual handlers see the same synthetic call/account objects."""
    store = CallbackStore()
    store.transfer_storage = call.transfer_storage
    row = call.records.call
    row.account_id, row.assistant_id = ACCOUNT_A, None
    for key, value in {
        "ended_at": None, "ended_early": False, "transfer_mode": None,
        "outcome": None, "recording_sid": None, "recording_url": None,
        "acw_completed_at": None, "acw_skip_reason": None,
    }.items():
        if not hasattr(row, key):
            setattr(row, key, value)
    account = call.records.rows["Account"]
    account.id = ACCOUNT_A
    store.rows["Account"][0] = account
    store.rows["CallLog"] = [row]
    leg = store.rows["CallLeg"][0]
    leg.call_log_id = row.id
    store.rows["CallLeg"] = [leg]
    return store


def test_signed_parent_hangup_stops_the_actual_worker_without_manual_cancellation():
    async def scenario():
        async with TransferCall() as call:
            await start_conversation(call)
            async with CallbackHarness(store=shared_store(call), handler=call.handler) as harness:
                response = await harness.post("/api/calls/status", {
                    "CallSid": CALL_SID, "CallStatus": "completed",
                }, token=TOKEN)
                assert response.status_code == 200, response.text
                await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
                assert call.records.call.status == "completed"
                assert len([
                    event for event in harness.store.rows["CallEvent"]
                    if event.event_type == "call_ended"
                ]) == 1
                # Replay must not start another worker or duplicate its end event.
                replay = await harness.post("/api/calls/status", {
                    "CallSid": CALL_SID, "CallStatus": "completed",
                }, token=TOKEN)
                assert replay.status_code == 200
                assert len(harness.store.rows["CallEvent"]) == 1
                assert not call.http.requests
                call.assert_clean()
    asyncio.run(scenario())


def test_foreign_account_signature_cannot_cancel_an_actual_active_worker():
    async def scenario():
        async with TransferCall() as call:
            await start_conversation(call)
            async with CallbackHarness(store=shared_store(call), handler=call.handler) as harness:
                response = await harness.post("/api/calls/status", {
                    "CallSid": CALL_SID, "CallStatus": "completed", "To": PHONE_B,
                }, token=TOKEN_B)
                assert response.status_code == 403
                assert call.handler.is_pipeline_active(CALL_SID)
                assert not call.run_task.done()
                assert call.records.call.status == "in_progress"
                assert harness.store.commits == 0
                assert not harness.jobs
                await call.finish("caller_hangup")
                call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_a_parent_signed_child_callback_without_attempt_binding_cannot_unlock_a_retry(source):
    async def scenario():
        async with TransferCall(source=source, outcome="timeout") as call:
            second = tool_reply(
                "transfer_fixture" if source == "tool" else "transfer_handoff",
            )
            second["tool_calls"][0]["id"] = "offline-transfer-retry"
            call.providers.replies = (call.providers.replies[0], second)
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await call.wait_until(
                lambda: result_for(call, "offline-transcript-tool") is not None
                and not call.created[3].user()._user_is_muted
            )
            async with CallbackHarness(store=shared_store(call), handler=call.handler) as harness:
                # Authenticity/parent correlation is not proof of WHICH issued
                # transfer attempt a delayed child callback describes.
                response = await harness.post("/api/calls/transfer-status", {
                    "CallSid": CHILD_A, "ParentCallSid": CALL_SID,
                    "CallStatus": "failed",
                }, token=TOKEN)
                twiml = next(
                    fields["Twiml"][0] for url, fields in call.http.requests
                    if url.endswith(f"/Calls/{CALL_SID}.json")
                )
                assert BASE_URL + "/api/calls/transfer-status" in twiml
                assert response.status_code == 200
                assert call.mapper._transfer_state == "unconfirmed"
                await call.providers.user_turn("Please try that connection again.", turn_index=1)
                await call.wait_until(
                    lambda: result_for(call, "offline-transfer-retry") is not None
                )
                assert result_for(call, "offline-transfer-retry")["status"] == "unconfirmed"
                updates = [
                    url for url, _ in call.http.requests
                    if url.endswith(f"/Calls/{CALL_SID}.json")
                ]
                assert len(updates) == 1
                await call.finish("caller_hangup")
                call.assert_clean(expected_errors=(
                    r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+"
                    if source == "tool" else r"Flow transfer failed: [\s\S]+",
                ))
    asyncio.run(scenario())

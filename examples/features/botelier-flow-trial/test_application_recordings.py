"""Recording eligibility and actual recording-start HTTP handling, all offline."""

import asyncio

import pytest

from lifecycle_io import CALL_SID
from test_application_transcripts import start_conversation
from transfer_io import RECORDING_SID, TransferCall


@pytest.mark.parametrize("enabled,entitled,want_start", [
    (False, False, False), (False, True, False),
    (True, False, False), (True, True, True),
])
def test_recording_requires_both_account_entitlement_and_assistant_toggle(
    enabled, entitled, want_start,
):
    """Either missing authorization condition must prevent recording HTTP entirely."""
    async def scenario():
        async with TransferCall(recording=enabled, entitled=entitled) as call:
            await start_conversation(call)
            if want_start:
                await call.wait_until(
                    lambda: call.handler.call_recording_sids.get(CALL_SID) == RECORDING_SID
                )
            await call.finish("caller_hangup")
            starts = [url for url, _ in call.http.requests if url.endswith("/Recordings.json")]
            assert len(starts) == (1 if want_start else 0)
            assert call.records.transfers == []
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", [503, "timeout", "invalid-json"])
def test_recording_start_failure_does_not_kill_the_voice_worker(outcome):
    """Optional recording refusal/timeout/malformed responses must remain nonfatal."""
    async def scenario():
        async with TransferCall(recording=True, start_outcome=outcome) as call:
            await start_conversation(call)
            await call.wait_until(lambda: call.http.started.is_set())
            task = call.handler.call_recording_tasks[CALL_SID]
            await task
            assert CALL_SID not in call.handler.call_recording_sids
            assert call.handler.is_pipeline_active(CALL_SID)
            await call.finish("caller_hangup")
            call.assert_clean()
    asyncio.run(scenario())

"""Duplicates, late delivery and hostile signed fields through actual routes."""

import asyncio
from datetime import timedelta

import pytest

from callback_io import CallbackHarness
from callback_store import CHILD_A, PARENT_A, PHONE_A, RECORDING, STARTED


RECORDING_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/AC" + "0" * 32
    + "/Recordings/" + RECORDING
)


@pytest.mark.parametrize("status", ["ringing", "in-progress"])
def test_late_nonterminal_parent_event_cannot_reopen_a_finished_call(status):
    async def scenario():
        async with CallbackHarness() as harness:
            row = harness.store.rows["CallLog"][0]
            row.status, row.ended_at = "completed", STARTED + timedelta(seconds=12)
            response = await harness.post("/api/calls/status", {
                "CallSid": PARENT_A, "CallStatus": status,
            })
            assert response.status_code == 200
            assert row.status == "completed"
            assert row.ended_at == STARTED + timedelta(seconds=12)
            assert not harness.store.rows["CallEvent"]
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
def test_late_child_event_cannot_reopen_the_leg_or_invent_a_connection(path):
    async def scenario():
        async with CallbackHarness() as harness:
            leg = harness.store.rows["CallLeg"][0]
            leg.status, leg.ended_at = "completed", STARTED + timedelta(seconds=12)
            response = await harness.post(path, {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "in-progress", "To": PHONE_A,
            })
            assert response.status_code == 200
            assert leg.status == "completed"
            assert leg.ended_at == STARTED + timedelta(seconds=12)
            assert not harness.store.rows["CallEvent"]
    asyncio.run(scenario())


def test_conflicting_terminal_child_event_cannot_rewrite_a_confirmed_result_or_cost_duration():
    async def scenario():
        async with CallbackHarness() as harness:
            parent, leg = harness.store.rows["CallLog"][0], harness.store.rows["CallLeg"][0]
            parent.outcome = "transferred"
            leg.status, leg.duration_seconds, leg.duration_source = "completed", 12, "twilio_webhook"
            response = await harness.post("/api/calls/transfer-status", {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "busy", "CallDuration": "0", "To": PHONE_A,
            })
            assert response.status_code == 200
            assert leg.status == "completed"
            assert leg.duration_seconds == 12
            assert parent.outcome == "transferred"
            assert not harness.store.rows["CallEvent"]
            assert not harness.billing
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
def test_repeated_child_completion_keeps_one_event_and_the_original_end_time(path):
    async def scenario():
        async with CallbackHarness() as harness:
            fields = {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "completed", "CallDuration": "12", "To": PHONE_A,
            }
            first = await harness.post(path, fields)
            assert first.status_code == 200
            ended_at = harness.store.rows["CallLeg"][0].ended_at
            second = await harness.post(path, fields)
            assert second.status_code == 200
            assert not harness.store.locked
            events = [
                event for event in harness.store.rows["CallEvent"]
                if event.event_type == "transfer_ended"
            ]
            assert len(events) == 1
            assert events[0].details["ChildCallSid"] == CHILD_A
            assert harness.store.rows["CallLeg"][0].ended_at == ended_at
    asyncio.run(scenario())


def test_late_authoritative_duration_is_saved_without_erasing_ended_early_classification():
    async def scenario():
        async with CallbackHarness() as harness:
            row = harness.store.rows["CallLog"][0]
            row.status, row.ended_at = "ended_early", STARTED + timedelta(seconds=12)
            response = await harness.post("/api/calls/status", {
                "CallSid": PARENT_A, "CallStatus": "completed", "CallDuration": "12",
            })
            assert response.status_code == 200
            assert row.status == "ended_early"
            assert row.ended_at == STARTED + timedelta(seconds=12)
            assert harness.billing[0][0] == "_upsert_inbound_billing"
            assert harness.billing[0][1][1] == 12
    asyncio.run(scenario())


def test_parent_progress_during_a_transfer_cannot_reopen_the_finished_ai_leg():
    from uuid import UUID
    from botelier.models import CallLeg

    async def scenario():
        async with CallbackHarness() as harness:
            row = harness.store.rows["CallLog"][0]
            row.status = "in_progress"
            ai_leg = CallLeg(
                id=UUID(int=31), call_log_id=row.id, call_sid=PARENT_A,
                leg_number=1, leg_type="ai_conversation", status="completed",
                started_at=STARTED, ended_at=STARTED + timedelta(seconds=12),
                duration_seconds=12, duration_source="pipecat",
            )
            harness.store.rows["CallLeg"].append(ai_leg)
            response = await harness.post("/api/calls/status", {
                "CallSid": PARENT_A, "CallStatus": "in-progress",
            })
            assert response.status_code == 200
            assert row.status == "in_progress"
            assert ai_leg.status == "completed"
            assert ai_leg.ended_at == STARTED + timedelta(seconds=12)
            assert ai_leg.duration_seconds == 12
            assert ai_leg.duration_source == "pipecat"
    asyncio.run(scenario())


def test_status_service_itself_rejects_a_known_child_of_another_parent():
    from botelier.services.call_logger import CallLogger
    from callback_store import CallbackStore, CHILD_B

    store = CallbackStore()
    assert CallLogger(store).update_leg_status(
        CHILD_B, "ringing", parent_call_sid=PARENT_A, to_number=PHONE_A,
    ) is False
    assert store.rows["CallLeg"][1].status == "initiated"
    assert store.commits == 0


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
def test_unknown_status_does_not_enter_the_stored_lifecycle(path):
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(path, {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "made-up-status", "To": PHONE_A,
            })
            assert response.status_code == 422
            assert harness.store.rows["CallLeg"][0].status == "initiated"
            assert harness.store.commits == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("path,fields,service_error,api_error", [
    ("/api/calls/status", {
        "CallSid": PARENT_A, "CallStatus": "ringing",
    }, "Error updating call status: synthetic_db_write_failure",
        "Call status callback persistence failed: RuntimeError"),
    ("/api/calls/transfer-status", {
        "CallSid": CHILD_A, "ParentCallSid": PARENT_A, "CallStatus": "ringing",
    }, "Error updating leg status: synthetic_db_write_failure",
        "Transfer status callback persistence failed: RuntimeError"),
    ("/api/calls/recording-status", {
        "CallSid": PARENT_A, "RecordingStatus": "completed",
        "RecordingSid": RECORDING, "RecordingUrl": RECORDING_URL,
    }, None, "Recording status callback persistence failed: RuntimeError"),
])
def test_persistence_failure_is_not_acknowledged_as_a_success(
    path, fields, service_error, api_error,
):
    from callback_store import CallbackStore

    class WriteFailureStore(CallbackStore):
        def commit(self):
            raise RuntimeError("synthetic_db_write_failure")

    async def scenario():
        async with CallbackHarness(
            store=WriteFailureStore(), expected_rollbacks=1,
            expected_errors=tuple(e for e in (service_error, api_error) if e),
        ) as harness:
            response = await harness.post(path, fields)
            assert response.status_code == 503
            assert "synthetic_db_write_failure" not in response.text
            assert not harness.jobs
            assert harness.store.rows["CallLog"][0].recording_url is None
            assert harness.store.rows["CallLeg"][0].status == "initiated"
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
def test_failed_event_write_can_be_retried_without_acknowledging_a_missing_event(path):
    from callback_store import CallbackStore

    class EventFailureStore(CallbackStore):
        attempts = 0

        def commit(self):
            self.attempts += 1
            if self.attempts == 2:
                raise RuntimeError("synthetic_event_write_failure")
            super().commit()

    async def scenario():
        async with CallbackHarness(
            store=EventFailureStore(), expected_rollbacks=1,
            expected_errors=(
                ("Call" if path.endswith("/status") else "Transfer")
                + " status callback persistence failed: RuntimeError",
            ),
        ) as harness:
            fields = {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "completed", "CallDuration": "12", "To": PHONE_A,
            }
            failed = await harness.post(path, fields)
            assert failed.status_code == 503
            assert "synthetic_event_write_failure" not in failed.text
            assert not harness.store.rows["CallEvent"]
            assert not harness.jobs
            retried = await harness.post(path, fields)
            assert retried.status_code == 200
            assert len(harness.store.rows["CallEvent"]) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["/api/calls/status", "/api/calls/transfer-status"])
@pytest.mark.parametrize("duration", ["-1", "not-a-duration", "2147483648"])
def test_invalid_signed_duration_is_rejected_before_state_changes(path, duration):
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post(path, {
                "CallSid": CHILD_A, "ParentCallSid": PARENT_A,
                "CallStatus": "completed", "CallDuration": duration, "To": PHONE_A,
            })
            assert response.status_code == 422
            assert harness.store.rows["CallLeg"][0].status == "initiated"
            assert harness.store.commits == 0
            assert not harness.jobs
    asyncio.run(scenario())


@pytest.mark.parametrize("suffix", ["", ".mp3", ".wav", "/"])
def test_repeated_recording_completion_is_idempotent_and_does_not_double_the_extension(suffix):
    async def scenario():
        async with CallbackHarness() as harness:
            fields = {
                "CallSid": PARENT_A, "RecordingStatus": "completed",
                "RecordingSid": RECORDING, "RecordingUrl": RECORDING_URL + suffix,
            }
            first = await harness.post("/api/calls/recording-status", fields)
            assert first.status_code == 200
            row = harness.store.rows["CallLog"][0]
            assert row.recording_url == RECORDING_URL + ".mp3"
            commits = harness.store.commits
            second = await harness.post("/api/calls/recording-status", fields)
            assert second.status_code == 200
            assert row.recording_sid == RECORDING
            assert harness.store.commits == commits
    asyncio.run(scenario())


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private",
    "https://api.twilio.com.attacker.invalid/recording",
    RECORDING_URL + "?redirect=http://127.0.0.1/",
    RECORDING_URL.replace(RECORDING, "RE" + "9" * 32),
])
def test_signed_recording_url_cannot_save_an_untrusted_or_mismatched_media_location(url):
    async def scenario():
        async with CallbackHarness() as harness:
            response = await harness.post("/api/calls/recording-status", {
                "CallSid": PARENT_A, "RecordingStatus": "completed",
                "RecordingSid": RECORDING, "RecordingUrl": url,
            })
            assert response.status_code == 422
            assert harness.store.rows["CallLog"][0].recording_url is None
            assert harness.store.commits == 0
    asyncio.run(scenario())


def test_a_conflicting_recording_cannot_silently_replace_a_previously_identified_recording():
    async def scenario():
        async with CallbackHarness() as harness:
            row = harness.store.rows["CallLog"][0]
            row.recording_sid, row.recording_url = RECORDING, RECORDING_URL + ".mp3"
            other = "RE" + "9" * 32
            response = await harness.post("/api/calls/recording-status", {
                "CallSid": PARENT_A, "RecordingStatus": "completed",
                "RecordingSid": other, "RecordingUrl": RECORDING_URL.replace(RECORDING, other),
            })
            assert response.status_code == 200
            assert response.json() == {"status": "ignored", "reason": "recording_conflict"}
            assert row.recording_sid == RECORDING
            assert row.recording_url == RECORDING_URL + ".mp3"
            assert harness.store.commits == 0
    asyncio.run(scenario())

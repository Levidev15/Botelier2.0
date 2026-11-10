"""An unconfirmed side effect must not be sent twice by a later model turn."""

import asyncio
import json

import pytest

from lifecycle_io import CALL_SID
from test_application_transcripts import start_conversation
from transcript_tools import tool_reply
from transfer_io import ANNOUNCEMENT, TransferCall


def result_for(call, tool_call_id):
    for message in call.created[4].messages:
        if (
            message.get("role") == "tool"
            and message.get("tool_call_id") == tool_call_id
            and message.get("content") != "IN_PROGRESS"
        ):
            return json.loads(message["content"])
    return None


@pytest.mark.parametrize("source", ["tool", "flow"])
@pytest.mark.parametrize("outcome", [500, "timeout"])
def test_later_model_turn_cannot_repeat_an_unconfirmed_transfer(source, outcome):
    """Removing the side-effect guard would issue a second real SDK update."""
    async def scenario():
        async with TransferCall(source=source, outcome=outcome) as call:
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

            await call.providers.user_turn("Please try that connection again.", turn_index=1)
            await call.wait_until(
                lambda: result_for(call, "offline-transfer-retry") is not None
                or len(call.marks()) == 2
            )
            # Drive the old unsafe implementation to its observable outcome;
            # emergency teardown is never the evidence for duplicate rejection.
            if len(call.marks()) == 2:
                call.acknowledge(call.marks()[1]["mark"]["name"])
            await call.wait_until(
                lambda: result_for(call, "offline-transfer-retry") is not None
            )
            updates = [
                url for url, _ in call.http.requests
                if url.endswith(f"/Calls/{CALL_SID}.json")
            ]
            assert len(updates) == 1, "A second model turn repeated an unconfirmed handoff"
            for tool_call_id in ("offline-transcript-tool", "offline-transfer-retry"):
                result = result_for(call, tool_call_id)
                assert result["status"] == "unconfirmed"
                assert result["retry_safe"] is False
            spoken = "".join(
                message.get("text", "") for message in call.providers.tts.sent
                if message.get("type") == "Speak"
            )
            assert spoken.count(ANNOUNCEMENT) == 1
            assert call.records.transfers == []
            await call.finish("caller_hangup")
            call.assert_clean(expected_errors=(
                r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+"
                if source == "tool" else r"Flow transfer failed: [\s\S]+",
            ))
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_an_explicit_new_turn_can_retry_after_a_definite_carrier_rejection(source):
    async def scenario():
        async with TransferCall(source=source, outcome=400) as call:
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
            assert result_for(call, "offline-transcript-tool")["status"] == "failed"
            call.http.outcome = 200
            await call.providers.user_turn("Please try that connection again.", turn_index=1)
            await call.wait_until(lambda: len(call.marks()) == 2)
            call.acknowledge(call.marks()[1]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert result_for(call, "offline-transfer-retry")["status"] == "transferred"
            assert len(call.records.transfers) == 1
            assert len([
                url for url, _ in call.http.requests
                if url.endswith(f"/Calls/{CALL_SID}.json")
            ]) == 2
            call.assert_clean(expected_errors=(
                r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+"
                if source == "tool" else r"Flow transfer failed: [\s\S]+",
            ))
    asyncio.run(scenario())

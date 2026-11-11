"""Recreated real workers must not repeat a remotely issued handoff."""

import asyncio
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from xml.etree import ElementTree

import pytest

from callback_io import CallbackHarness
from lifecycle_io import CALL_SID
from test_application_callback_lifecycle import shared_store
from test_application_transcripts import start_conversation
from test_application_transfer_retries import result_for
from transfer_io import TOKEN, TransferCall
from transfer_storage import MemoryTransferStorage


def carrier_updates(call):
    return [
        values for url, values in call.http.requests
        if url.endswith(f"/Calls/{CALL_SID}.json")
    ]


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_generated_callback_identifies_the_persisted_transfer_attempt(source):
    async def scenario():
        async with TransferCall(source=source) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            number = ElementTree.fromstring(carrier_updates(call)[0]["Twiml"][0]).find(".//Number")
            query = parse_qs(urlsplit(number.attrib["statusCallback"]).query)
            assert len(query.get("transfer_attempt", [])) == 1, "Callback has no attempt identity"
            assert str(UUID(query["transfer_attempt"][0])) == query["transfer_attempt"][0]
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_recreated_worker_cannot_repeat_a_transfer_whose_response_was_lost(source):
    async def scenario():
        issued = []
        storage = MemoryTransferStorage()
        for index, outcome in enumerate(("timeout", 200)):
            async with TransferCall(source=source, outcome=outcome, transfer_storage=storage) as call:
                await start_conversation(call)
                await call.providers.user_turn()
                await call.wait_until(
                    lambda: bool(call.marks())
                    or result_for(call, "offline-transcript-tool") is not None
                )
                if call.marks():
                    call.acknowledge(call.marks()[0]["mark"]["name"])
                await call.wait_until(
                    lambda: result_for(call, "offline-transcript-tool") is not None
                )
                issued.extend(carrier_updates(call))
                if not call.run_task.done():
                    await call.finish("caller_hangup")
                else:
                    await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
                call.assert_clean(expected_errors=(
                    (r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+"
                     if source == "tool" else r"Flow transfer failed: [\s\S]+"),
                ) if index == 0 else ())
        assert len(issued) == 1, "Recreating a worker repeated the issued transfer"
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["tool", "flow"])
def test_disconnect_cannot_hang_up_an_accepted_transfer_before_its_local_log(source):
    async def scenario():
        async with TransferCall(source=source) as call:
            call.records.fail_transfer_write = True
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(lambda: len(call.marks()) == 1)
            call.acknowledge(call.marks()[0]["mark"]["name"])
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=5)
            assert len(carrier_updates(call)) == 1
            assert not call.records.call.has_transfer
            async with CallbackHarness(store=shared_store(call), handler=call.handler) as harness:
                response = await harness.post("/api/calls/connect-complete", {
                    "CallSid": CALL_SID,
                }, token=TOKEN)
                assert response.status_code == 200
                assert "Hangup" not in response.text, "Late bookkeeping hung up the accepted bridge"
                assert not harness.jobs, "Unconfirmed transfer was prematurely finalized"
            call.assert_clean(expected_errors=(
                r"Accepted transfer follow-up failed for call offline-lifecycle-call: RuntimeError"
                if source == "tool" else r"Accepted flow transfer follow-up failed: RuntimeError",
            ))
    asyncio.run(scenario())

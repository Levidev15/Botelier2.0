"""First CI process: lose the response/final persistence after an issued update."""

import asyncio
from unittest.mock import patch

from botelier.services.transfer_attempts import TransferAttempts
from lifecycle_io import CALL_SID
from recovery_postgres import ACCOUNT, PostgresTransferStorage
from test_application_transcripts import start_conversation
from test_application_transfer_recovery import carrier_updates
from test_application_transfer_retries import result_for
from transfer_io import TransferCall


def test_first_process_leaves_a_committed_issued_attempt_without_an_outcome():
    async def scenario():
        storage = PostgresTransferStorage()
        try:
            async with TransferCall(outcome="timeout", transfer_storage=storage) as call:
                await start_conversation(call)
                # Simulate the crash window: the issued marker committed, but
                # the caller never persisted an HTTP outcome. The next CI
                # container has no Python object or memory from this process.
                with patch.object(
                    call.mapper._transfer_attempts(), "settle",
                    side_effect=RuntimeError("Synthetic worker loss before outcome persistence"),
                ):
                    await call.providers.user_turn()
                    await call.wait_until(lambda: len(call.marks()) == 1)
                    call.acknowledge(call.marks()[0]["mark"]["name"])
                    await call.wait_until(lambda: result_for(call, "offline-transcript-tool") is not None)
                assert len(carrier_updates(call)) == 1
                assert TransferAttempts(storage).get(ACCOUNT, CALL_SID).phase == "issued"
                await call.finish("caller_hangup")
                call.assert_clean(expected_errors=(
                    r"❌ Twilio transfer failed for call offline-lifecycle-call: [\s\S]+",
                    r"Transfer outcome persistence unavailable: RuntimeError",
                ))
        finally:
            storage.close()
    asyncio.run(scenario())

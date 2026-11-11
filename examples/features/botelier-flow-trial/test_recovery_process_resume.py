"""Second CI process/container: no old Python state or connections survive."""

import asyncio

from botelier.services.transfer_attempts import TransferAttempts
from lifecycle_io import CALL_SID
from recovery_postgres import ACCOUNT, PostgresTransferStorage
from test_application_transcripts import start_conversation
from test_application_transfer_recovery import carrier_updates
from test_application_transfer_retries import result_for
from transfer_io import TransferCall


def test_fresh_process_cannot_repeat_the_first_process_issued_transfer():
    async def scenario():
        storage = PostgresTransferStorage(reset=False)
        try:
            before = TransferAttempts(storage).get(ACCOUNT, CALL_SID)
            assert before is not None and before.phase == "issued"
            # A different transfer path cannot bypass the stable call-wide key.
            async with TransferCall(source="flow", transfer_storage=storage) as call:
                await start_conversation(call)
                await call.providers.user_turn("Please try that connection again.")
                await call.wait_until(lambda: result_for(call, "offline-transcript-tool") is not None)
                assert carrier_updates(call) == []
                assert not call.marks()
                result = result_for(call, "offline-transcript-tool")
                assert result["status"] == "unconfirmed"
                assert result["retry_safe"] is False
                assert TransferAttempts(storage).get(ACCOUNT, CALL_SID).attempt_id == before.attempt_id
                await call.finish("caller_hangup")
                call.assert_clean()
        finally:
            storage.close()
    asyncio.run(scenario())

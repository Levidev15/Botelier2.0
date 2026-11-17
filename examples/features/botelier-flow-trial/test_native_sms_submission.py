"""Known no-submit outcomes must not become unknown or be sent on replay."""

import asyncio
import threading

import pytest

from test_native_quote_delivery import (
    _add_tool_and_sender, _confirmed_facts, _delivery_definition,
    _fixed_quote_clock, _held_sms_client, _ledger_rows, _runner,
    _use_vetted_offline_sentence_assets,
)


@pytest.mark.parametrize("fault", ["failed", "invalid"])
def test_sms_guard_fault_is_a_known_rejected_receipt_not_unknown(monkeypatch, fault):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-guard-" + fault
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled)
            original_send = runner.messenger.send_sms

            def faulty_guard():
                if fault == "failed":
                    raise RuntimeError("Synthetic internal guard fault")
                return False

            async def inject_guard_fault(recipient, body, *, before_submit=None):
                assert callable(before_submit)
                return await original_send(recipient, body, before_submit=faulty_guard)

            runner.messenger.send_sms = inject_guard_fault
            facts, confirmation = _confirmed_facts("caller_phone")
            first = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            reason = "pre_submit_guard_" + fault
            assert first.success is False and first.failure_reason == reason
            assert sent == []
            assert [row.status for row in _ledger_rows(fixture)] == ["failed"]
            retry = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert retry.success is False and retry.failure_reason == reason
            assert sent == []
            assert len(_ledger_rows(fixture)) == 1
            await runner.close()

    asyncio.run(scenario())


def test_sms_timeout_before_the_submission_boundary_is_known_no_submit(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-timeout-before-submit"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            entered, release, finished = (
                threading.Event(), threading.Event(), threading.Event(),
            )
            sent = []
            runner, _ = _runner(
                fixture, compiled,
                sms_client=_held_sms_client(entered, release, sent),
            )
            runner.messenger.timeout = 0.15
            original_submit = runner.messenger._submit_sms

            def track_worker(*args):
                try:
                    return original_submit(*args)
                finally:
                    finished.set()

            runner.messenger._submit_sms = track_worker
            facts, confirmation = _confirmed_facts("caller_phone")
            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            try:
                assert await asyncio.wait_for(
                    asyncio.to_thread(entered.wait, 3), timeout=4,
                )
                result = await task
            finally:
                release.set()
            assert await asyncio.wait_for(
                asyncio.to_thread(finished.wait, 3), timeout=4,
            )
            assert result.success is False
            assert result.failure_reason == "submission_cancelled"
            assert [row.status for row in _ledger_rows(fixture)] == ["failed"]
            assert sent == []
            retry = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert retry.failure_reason == "submission_cancelled"
            assert sent == [] and len(_ledger_rows(fixture)) == 1
            await runner.close()

    asyncio.run(scenario())

"""Full native quote rehearsal uses samples but never a real effect provider."""

import asyncio
import json
from copy import deepcopy

import pytest

from native_booking_io import RECIPIENTS, ROOMS, STAY, authoritative_quote, seed_booking
from test_native_quote_delivery import _fixed_quote_clock, _use_vetted_offline_sentence_assets


@pytest.mark.parametrize("delivery_type", ["SEND_SMS", "SEND_EMAIL"])
def test_full_quote_link_graph_previews_http_delivery_and_record_without_calllog(
    monkeypatch, delivery_type,
):
    import guard as provider_guard
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            from botelier.models.call_log import CallLog
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_action_preview import NativeActionPreview
            from botelier.voice.flows.native_action_preview import NativePreviewResponse
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeTerminalResult
            from botelier.voice.flows.native_graph import compile_flow
            from native_graph_io import GraphProviders, NativeGraphPipelineCall
            from node_contract_io import speech, tool_delta

            _fixed_quote_clock(monkeypatch, [NOW])
            source = seed_booking(fixture, delivery_type)
            db = fixture.factory()
            try:
                db.query(CallLog).filter(
                    CallLog.call_sid == fixture.identity.call_sid,
                ).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()
            compiled = compile_flow(source, fixture.identity)
            quote = authoritative_quote()
            preview = NativeActionPreview(timeout=15)
            holder = {}
            runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
                channel="simulation", preview=preview,
                preview_scope=lambda node: (
                    str(compiled.identity.tool_id),
                    str(compiled.identity.flow_version_id),
                    str(holder["call"].adapter._revision),
                    str(id(holder["call"].adapter._visit)),
                ),
            )
            stay_replies = [
                tool_delta("collect_stay", STAY),
            ]
            providers = GraphProviders([
                *stay_replies,
                tool_delta("select_room", {"ordinal": 2, "label": "Ocean Suite"}),
                tool_delta("collect_contact", {
                    "caller_email" if delivery_type == "SEND_EMAIL" else "caller_phone":
                        RECIPIENTS[delivery_type],
                }),
                tool_delta("confirm", {"response": "yes"}),
            ])
            submissions = []

            async def fake_business_io(_transport, request):
                raise AssertionError(f"preview attempted business HTTP: {request.url}")

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", fake_business_io,
            )

            async def terminal(node, _facts):
                return NativeTerminalResult(
                    node.type == "end", completed=node.type == "end",
                    failure_reason=None if node.type == "end" else "preview_only_transfer",
                )

            call = NativeGraphPipelineCall(
                compiled, providers=providers, execute_action=runner.execute,
                terminal_handler=terminal,
            )
            holder["call"] = call

            async def finish_sample(node_id, data):
                await call.wait_until(lambda: preview.snapshot() is not None)
                pending = preview.snapshot()
                assert pending["node_id"] == node_id
                submissions.append(pending["source_kind"])
                preview.submit(
                    pending["request_id"], NativePreviewResponse(
                        status_code=200, data=data,
                    ),
                )

            async with call:
                await call.activate()
                await providers.user_turn(
                    "From December 1, 2026 to December 3, 2026, for two adults and no children.",
                    turn_index=0,
                )
                await finish_sample("availability", {"rooms": deepcopy(ROOMS)})
                await call.wait_until(
                    lambda: call.adapter.manager.current_node == "picker",
                )

                await providers.user_turn(
                    "The second room, Ocean Suite", turn_index=1,
                )
                await finish_sample("fetch_quote", {
                    "reservation": deepcopy(quote), "status": "quote_ready",
                })
                await call.wait_until(
                    lambda: call.adapter.manager.current_node == "contact",
                )

                await providers.user_turn(
                    RECIPIENTS[delivery_type], turn_index=2,
                )
                await call.wait_until(
                    lambda: call.adapter.manager.current_node == "confirm",
                )
                await providers.user_turn("Yes.", turn_index=3)
                await finish_sample("delivery", {"status": "accepted"})
                await call.wait_until(lambda: call.adapter.snapshot()["completed"])
                await call.wait_until(lambda: call.adapter.manager.current_node == "done")

                assert submissions == ["http", "http", "tool"]
                assert [item["kind"] for item in preview.effects] == [
                    "api_request", "api_request",
                    "send_email" if delivery_type == "SEND_EMAIL" else "send_sms",
                    "record_create",
                ]
                assert all(item["simulated"] for item in preview.effects)
                assert preview.get_record("save") is not None
                assert call.adapter.facts["quote_total"] == "230.00"
                recipient_variable = (
                    "caller_email" if delivery_type == "SEND_EMAIL" else "caller_phone"
                )
                assert RECIPIENTS[delivery_type] == call.adapter.facts[recipient_variable]
                assert preview.snapshot() is None

                db = fixture.factory()
                try:
                    assert db.query(fixture.effect_models["Record"]).count() == 0
                    assert db.query(
                        fixture.effect_models["OperationIdempotency"],
                    ).count() == 0
                finally:
                    db.close()
                assert runner.messenger is None
                assert providers.business_requests == []
                public_trace = json.dumps({
                    "requests": providers.requests,
                    "context": call.created[4].get_messages(),
                    "speech": speech(call),
                }, default=str)
                assert quote["checkout_url"] not in public_trace
                assert call.adapter.facts["quote_fingerprint"] not in public_trace
                await call.finish(ending="graceful_end")
                await call.adapter.close()
                await runner.close()
            call.assert_clean()

    denials = len(provider_guard.BLOCKED)
    try:
        asyncio.run(asyncio.wait_for(scenario(), 90))
    finally:
        assert len(provider_guard.BLOCKED) == denials, provider_guard.BLOCKED[denials:]

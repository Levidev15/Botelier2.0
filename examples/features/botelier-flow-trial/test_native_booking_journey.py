"""Real SDK/controller/broker/ORM reference journey with fake provider I/O."""

import asyncio
import html
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from native_booking_io import RECIPIENTS, ROOMS, STAY, authoritative_quote, seed_booking
from test_native_quote_delivery import (
    _fixed_quote_clock, _ledger_rows, _runner, _use_vetted_offline_sentence_assets,
)


@pytest.mark.parametrize("availability_source", ["http", "mcp"])
@pytest.mark.parametrize("delivery_type", ["SEND_SMS", "SEND_EMAIL"])
@pytest.mark.parametrize("batch_stay", [False, True])
def test_booking_link_uses_real_sdk_broker_and_record_without_creating_payment(
    monkeypatch, availability_source, delivery_type, batch_stay,
):
    import guard as provider_guard
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_execution import NativeConfirmation, NativeTerminalResult
            from botelier.voice.flows.native_graph import compile_flow
            from native_graph_io import GraphProviders, NativeGraphPipelineCall
            from node_contract_io import speech, tool_delta

            _fixed_quote_clock(monkeypatch, [NOW])
            source = seed_booking(
                fixture, delivery_type, mcp=availability_source == "mcp",
            )
            compiled = compile_flow(source, fixture.identity)
            recipient_variable = "caller_email" if delivery_type == "SEND_EMAIL" else "caller_phone"
            stay_replies = [tool_delta("collect_stay", STAY)] if batch_stay else [
                tool_delta("collect_check_in", {"check_in": STAY["check_in"]}),
                tool_delta("collect_check_out", {"check_out": STAY["check_out"]}),
                tool_delta("collect_adults", {"adults": 2}),
                tool_delta("collect_children", {"children": 0}),
            ]
            providers = GraphProviders([
                *stay_replies,
                tool_delta("select_room", {"ordinal": 2, "label": "Ocean Suite"}),
                tool_delta("collect_contact", {recipient_variable: RECIPIENTS[delivery_type]}),
                tool_delta("confirm", {"response": "yes"}),
                "Please say yes to send the review link, or no to stop.",
                tool_delta("confirm", {"response": "yes"}),
            ])
            provider_failures = []
            original_provider_http = providers.http

            async def observed_provider_http(request):
                try:
                    return await original_provider_http(request)
                except Exception as exc:
                    provider_failures.append((type(exc).__name__, str(exc)[:240]))
                    raise

            providers.http = observed_provider_http
            http_requests, mcp_calls = [], []
            quote = authoritative_quote()

            async def fake_pms(request):
                assert request.method == "GET"
                assert request.url.host == "pms.example.invalid"
                http_requests.append(request)
                assert all(request.url.params[key] == str(value) for key, value in STAY.items())
                if request.url.path == "/availability":
                    assert availability_source == "http"
                    return httpx.Response(200, json={"rooms": deepcopy(ROOMS)}, request=request)
                assert request.url.path == "/reservations/quote"
                assert request.url.params["room_id"] == "suite"
                assert request.url.params["rate_id"] == "flexible"
                return httpx.Response(200, json={
                    "reservation": deepcopy(quote), "status": "quote_ready",
                }, request=request)

            transport = httpx.MockTransport(fake_pms)

            async def fake_business_io(_transport, request):
                return await transport.handle_async_request(request)

            monkeypatch.setattr(SSRFSafeTransport, "handle_async_request", fake_business_io)

            class MCPSession:
                async def list_tools(self):
                    return SimpleNamespace(tools=[SimpleNamespace(
                        name="availability", inputSchema={
                            "type": "object", "properties": {
                                key: {"type": "string" if "check_" in key else "integer"} for key in STAY
                            }, "required": list(STAY),
                        },
                    )])

                async def call_tool(self, name, arguments):
                    assert name == "availability"
                    mcp_calls.append(deepcopy(arguments))
                    return SimpleNamespace(
                        isError=False, structuredContent={"rooms": deepcopy(ROOMS)}, content=[],
                    )

            class MCPClient:
                def __init__(self, **_kwargs):
                    self._session = MCPSession()

                async def connect(self, timeout):
                    assert timeout == 10
                    return True, None

                async def disconnect(self):
                    return None

            runner, sent = _runner(fixture, compiled, email=delivery_type == "SEND_EMAIL")
            runner.mcp_client_factory = MCPClient
            actions, results, terminal_nodes, confirmations = [], [], [], []
            holder = {}

            async def execute(node, facts, *, confirmation):
                actions.append(node.node_id)
                if node.node_id in {"delivery", "save"}:
                    assert isinstance(confirmation, NativeConfirmation)
                    confirmations.append(confirmation)
                result = await runner.execute(node, facts, confirmation=confirmation)
                results.append((node.node_id, result))
                return result

            async def terminal(node, _facts):
                call = holder["call"]
                closing = node.data().get("closingMessage")
                if closing:
                    await call.wait_until(lambda: closing in speech(call))
                terminal_nodes.append(node.node_id)
                return NativeTerminalResult(True, completed=True)

            call = NativeGraphPipelineCall(
                compiled, providers=providers, execute_action=execute, terminal_handler=terminal,
            )
            holder["call"] = call
            async with call:
                await call.activate()

                def native_tools():
                    tools = getattr(call.created[4], "tools", None)
                    return {
                        item.name for item in getattr(tools, "standard_tools", ())
                        if item.name.startswith("native_")
                    }

                await call.wait_until(lambda: bool(native_tools()))
                turns = [(
                    "From December 1, 2026 to December 3, 2026, for two adults and no children.",
                    "picker",
                )] if batch_stay else [
                    ("December 1, 2026", "stay"), ("December 3, 2026", "stay"),
                    ("Two adults", "stay"), ("No children", "picker"),
                ]
                turns += [
                    ("The second room, Ocean Suite", "contact"),
                    (RECIPIENTS[delivery_type], "confirm"),
                ]
                for index, (text, target) in enumerate(turns):
                    prior = native_tools()
                    await providers.user_turn(text, turn_index=index)
                    try:
                        await call.wait_until(lambda: (
                            call.adapter.manager.current_node == target and native_tools() != prior
                        ))
                    except TimeoutError as exc:
                        snapshot = call.adapter.snapshot()
                        raise AssertionError({
                            "turn": index, "expected_node": target,
                            "actual_node": snapshot["current_node"],
                            "status": snapshot["status"], "failure_reason": snapshot["failure_reason"],
                            "actions": [(name, result.failure_reason) for name, result in results],
                            "provider_failures": provider_failures,
                            "model_request_count": len(providers.requests),
                        }) from exc
                assert actions == ["availability", "fetch_quote", "validate_quote"], [
                    (name, result.failure_reason) for name, result in results
                ]
                assert sent == [] and _ledger_rows(fixture) == []
                db = fixture.factory()
                assert db.query(fixture.effect_models["Record"]).count() == 0
                db.close()

                # A model-produced "yes" must not override the actual caller's qualified refusal.
                prior_results = sum(
                    message.get("role") == "tool" for message in call.created[4].get_messages()
                )
                await providers.user_turn("Yes, but I need to change the room.", turn_index=len(turns))
                await call.wait_until(lambda: sum(
                    message.get("role") == "tool" for message in call.created[4].get_messages()
                ) > prior_results)
                await call.wait_until(lambda: (
                    "Please say yes to send the review link, or no to stop." in speech(call)
                ))
                assert call.adapter.manager.current_node == "confirm"
                assert sent == [] and _ledger_rows(fixture) == []
                assert actions == ["availability", "fetch_quote", "validate_quote"]

                await providers.user_turn("Yes.", turn_index=len(turns) + 1)
                await call.wait_until(lambda: (
                    call.adapter.snapshot()["completed"]
                    and call.adapter.manager.current_node == "done"
                ))
                # The real host also sends one non-streaming, one-token warmup;
                # it must not be confused with or consume a scripted caller turn.
                warmups = [request for request in providers.requests if not request.get("stream")]
                assert len(warmups) == 1 and warmups[0]["max_tokens"] == 1
                assert actions == [
                    "availability", "fetch_quote", "validate_quote", "delivery", "save",
                ], [(name, result.failure_reason) for name, result in results]
                assert all(result.success for _name, result in results)
                assert terminal_nodes == ["done"]
                assert len(sent) == 1
                message = sent[0]
                assert message["body"].count(quote["checkout_url"]) == 1
                assert all(value in message["body"] for value in [
                    "Ocean Suite", "230.00", "200.00", "20.00", "10.00",
                    STAY["check_in"], STAY["check_out"],
                ])
                if delivery_type == "SEND_EMAIL":
                    assert html.escape(quote["checkout_url"]) in message["body_html"]
                    assert message["recipients"] == [RECIPIENTS[delivery_type]]
                else:
                    assert message["to"] == RECIPIENTS[delivery_type]

                db = fixture.factory()
                rows = db.query(fixture.effect_models["Record"]).all()
                assert len(rows) == 1
                assert rows[0].data == {
                    "room_id": "suite", "check_in": STAY["check_in"], "check_out": STAY["check_out"],
                    "adults": 2, "children": 0, "pricing_currency": "USD", "pricing_basis": "stay",
                    "pricing_subtotal": "200.00", "pricing_tax_total": "20.00",
                    "pricing_tax_treatment": "exclusive", "pricing_fees_total": "10.00",
                    "pricing_fees_treatment": "exclusive", "pricing_total": "230.00",
                    "room_name": "Ocean Suite", "recipient": RECIPIENTS[delivery_type],
                }
                assert rows[0].status == "link_accepted"
                assert str(rows[0].account_id) == fixture.account_id
                linked_call = db.query(fixture.effect_models["CallLog"]).filter(
                    fixture.effect_models["CallLog"].id == rows[0].source_call_log_id,
                ).one()
                assert str(linked_call.account_id) == fixture.account_id
                assert str(linked_call.assistant_id) == fixture.assistant_id
                assert linked_call.call_sid == fixture.identity.call_sid
                db.close()
                receipts = [
                    row for row in _ledger_rows(fixture)
                    if row.operation == runner._ledger._operation("delivery")
                ]
                assert len(receipts) == 1 and receipts[0].status == "succeeded"
                for node_id in ("delivery", "save"):
                    replay = await runner.execute(
                        compiled.node(node_id), call.adapter.facts, confirmation=confirmations[-1],
                    )
                    assert replay.success is True
                assert len(sent) == 1
                db = fixture.factory()
                assert db.query(fixture.effect_models["Record"]).count() == 1
                db.close()

                model_and_speech = json.dumps({
                    "requests": providers.requests, "context": call.created[4].get_messages(),
                    "speech": speech(call),
                }, default=str)
                assert quote["checkout_url"] not in model_and_speech
                assert html.unescape(quote["checkout_url"]) not in model_and_speech
                assert call.adapter.facts["quote_fingerprint"] not in model_and_speech
                assert len([request for request in providers.requests if request.get("stream")]) == len(stay_replies) + 5
                assert providers.business_requests == []
                assert len(http_requests) == (1 if availability_source == "mcp" else 2)
                assert mcp_calls == ([STAY] if availability_source == "mcp" else [])
                await call.finish(ending="graceful_end")
                await call.adapter.close()
                await runner.close()
            call.assert_clean()

    logical_denials = len(provider_guard.BLOCKED)
    try:
        asyncio.run(asyncio.wait_for(scenario(), 75))
    finally:
        assert len(provider_guard.BLOCKED) == logical_denials, (
            "The composed SDK provider fake denied an unexpected operation",
            provider_guard.BLOCKED[logical_denials:],
        )

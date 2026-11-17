import asyncio
import json
import uuid

import httpx


def test_native_read_and_mutating_capabilities_use_scoped_resolver_and_strict_claim(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        requests = []

        async def controlled_transport(_transport, request):
            requests.append(request)
            if request.url.path == "/availability":
                return httpx.Response(200, json={"amount": 0}, request=request)
            return httpx.Response(
                200, json={"confirmation": "R-123"}, request=request,
            )

        async with NativeEffectsFixture() as fixture:
            from botelier.models.integration import (
                AccountIntegration, IntegrationStatus, IntegrationType,
            )
            from botelier.models.operation_policy import ConnectionOperationPolicy
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow
            from editor_fixture import TOOL_SET_ID

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            connection_id = uuid.uuid4()
            integration_type_id = uuid.uuid4()
            endpoints = [
                {
                    "id": "availability", "method": "GET", "path": "/availability",
                    "capability": "search_availability",
                    "capability_params": {
                        "check_in_date": "arrival",
                        "check_out_date": "departure",
                    },
                    "query_params": [
                        {"key": "arrival", "value": "{{arrival}}", "required": True},
                        {"key": "departure", "value": "{{departure}}", "required": True},
                    ],
                },
                {
                    "id": "booking", "method": "POST", "path": "/booking",
                    "capability": "book_reservation",
                    "capability_params": {
                        "guest_first_name": "first_name",
                        "guest_last_name": "last_name",
                        "check_in_date": "arrival",
                        "check_out_date": "departure",
                        "room_type": "room",
                        "rate_code": "rate",
                    },
                    "body_template": (
                        '{"first":"{{first_name}}","last":"{{last_name}}",'
                        '"arrival":"{{arrival}}","departure":"{{departure}}",'
                        '"room":"{{room}}","rate":"{{rate}}"}'
                    ),
                },
            ]
            db = fixture.factory()
            integration_type = IntegrationType(
                id=integration_type_id, slug="capability-pms",
                name="Capability PMS", provider="fixture", auth_type="none",
                is_enabled=True, origin="customer_imported",
            )
            integration_type.set_endpoints(endpoints)
            connection = AccountIntegration(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                integration_type_id=integration_type_id,
                property_id=uuid.UUID(fixture.property_id),
                status=IntegrationStatus.CONNECTED,
                connection_config='{"base_url":"https://api.fixture.invalid"}',
            )
            db.add_all([integration_type, connection])
            db.add_all([
                ConnectionOperationPolicy(
                    account_integration_id=connection_id,
                    operation_id="availability", enabled=True,
                    risk_level="read", allowed_channels=["voice"],
                    test_status="passed", test_passed=True,
                    response_mapping={"amount": "$.amount"},
                ),
                ConnectionOperationPolicy(
                    account_integration_id=connection_id,
                    operation_id="booking", enabled=True,
                    risk_level="write", allowed_channels=["voice"],
                    test_status="passed", test_passed=True,
                    response_mapping={"confirmation": "$.confirmation"},
                ),
            ])
            capability_tool_id = uuid.uuid4()
            db.add(Tool(
                id=str(capability_tool_id), name="Search availability",
                description="Check room availability", tool_type=ToolType.CAPABILITY,
                config={"capability": "search_availability"},
                tool_set_id=uuid.UUID(TOOL_SET_ID), is_active="true",
            ))
            db.commit()
            db.close()

            facts = {
                "check_in_date": "2027-01-02", "check_out_date": "2027-01-04",
                "guest_first_name": "Ari", "guest_last_name": "Guest",
                "room_type": "king", "rate_code": "flex",
            }
            config = {
                "initial_node": "start",
                "variables": [
                    {"key": key, "type": "text"}
                    for key in facts
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "availability", "type": "api_request", "data": {"api": {
                        "apiSource": "capability", "capability": "search_availability",
                        "responseMapping": {"amount": "$.amount"},
                    }}},
                    {"id": "capability-tool", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": str(capability_tool_id),
                        "argumentsTemplate": (
                            '{"check_in_date":"{{check_in_date}}",'
                            '"check_out_date":"{{check_out_date}}"}'
                        ),
                        "responseMapping": {"amount": "$.amount"},
                    }}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Book {{room_type}} for {{guest_first_name}}?",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": list(facts),
                            "allowEdit": False,
                        },
                    }},
                    {"id": "book", "type": "api_request", "data": {"api": {
                        "apiSource": "capability", "capability": "book_reservation",
                        "responseMapping": {"confirmation": "$.confirmation"},
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-availability", "source": "start", "target": "availability"},
                    {"id": "availability-confirm", "source": "availability",
                     "target": "capability-tool", "sourceHandle": "success"},
                    {"id": "capability-confirm", "source": "capability-tool",
                     "target": "confirm", "sourceHandle": "success"},
                    {"id": "confirm-book", "source": "confirm", "target": "book",
                     "sourceHandle": "confirmed"},
                    {"id": "book-done", "source": "book", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            read = await runner.execute(
                compiled.node("availability"), facts,
            )
            assert read.success is True, read
            assert read.variables == {"amount": 0}
            assert requests[0].url.path == "/availability"
            assert requests[0].url.params["arrival"] == facts["check_in_date"]
            capability_tool = await runner.execute(
                compiled.node("capability-tool"), facts,
            )
            assert capability_tool.success is True, capability_tool
            assert capability_tool.variables == {"amount": 0}
            assert requests[1].url.path == "/availability"

            denied = await runner.execute(compiled.node("book"), facts)
            assert denied.failure_reason == "confirmation_required"
            assert len(requests) == 2
            db = fixture.factory()
            assert db.query(
                fixture.effect_models["OperationIdempotency"],
            ).count() == 0
            db.close()

            consent = NativeConfirmation(
                "confirm", 1, json.dumps(facts), tuple(facts),
            )
            accepted = await runner.execute(
                compiled.node("book"), facts, confirmation=consent,
            )
            replay = await runner.execute(
                compiled.node("book"), facts, confirmation=consent,
            )
            assert accepted.success is True, accepted
            assert accepted.variables == {"confirmation": "R-123"}
            assert replay == accepted
            assert len(requests) == 3
            assert requests[2].method == "POST"

    asyncio.run(scenario())

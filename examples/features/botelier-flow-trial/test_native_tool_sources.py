import asyncio
import uuid

import httpx
import pytest


def test_selected_owned_api_request_tool_uses_current_config_and_exact_outputs(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        requests = []

        async def controlled_transport(_transport, request):
            requests.append(request)
            return httpx.Response(
                200,
                json={"amount": 0, "private_card": "never expose"},
                request=request,
            )

        async with NativeEffectsFixture() as fixture:
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow
            from editor_fixture import TOOL_SET_ID

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            tool_id = uuid.uuid4()
            db = fixture.factory()
            target = Tool(
                id=str(tool_id), name="Owned catalog lookup",
                description="Read an owned item", tool_type=ToolType.API_REQUEST,
                config={
                    "method": "GET",
                    "url": "https://api.fixture.invalid/items/{{query}}",
                    "parameters": {"query": {"type": "string", "required": True}},
                    "responseMapping": {"amount": "$.amount"},
                    "timeout": 2, "retryCount": 0,
                },
                tool_set_id=uuid.UUID(TOOL_SET_ID), is_active="true",
            )
            db.add(target)
            db.commit()
            db.close()
            config = {
                "initial_node": "start",
                "variables": [{"key": "query", "type": "text"}],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "lookup", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": str(tool_id),
                        "argumentsTemplate": '{"query":"{{query}}"}',
                        "responseMapping": {"amount": "$.amount"},
                        "responseProjection": {
                            "fields": [{"variable": "amount"}],
                        },
                    }}},
                ],
                "edges": [{"id": "start-lookup", "source": "start", "target": "lookup"}],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            from botelier.voice.flows.native_tool_actions import NativeToolActionHandler

            mappings = NativeToolActionHandler(runner)._approved_mappings(
                compiled.node("lookup").data()["api"],
                {"amount": "$.amount"},
            )
            assert [(item.variable_key, item.json_path) for item in mappings] == [
                ("amount", "$.amount"),
            ]
            result = await runner.execute(
                compiled.node("lookup"), {"query": "A B/1"},
            )
            assert result.success is True, result
            assert result.variables == {"amount": 0}
            assert result.llm_data == {"amount": 0}
            assert len(requests) == 1
            assert requests[0].url.raw_path == b"/items/A%20B%2F1"
            assert "private_card" not in repr(result)

            preview = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview_result = await preview.execute(
                compiled.node("lookup"), {"query": "standard"},
            )
            assert preview_result.failure_reason == "preview_required"
            assert len(requests) == 1

    asyncio.run(scenario())


def test_selected_tool_cannot_override_its_published_output_map(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        calls = []

        async def controlled_transport(_transport, request):
            calls.append(request)
            return httpx.Response(200, json={"amount": 5, "secret": "blocked"}, request=request)

        async with NativeEffectsFixture() as fixture:
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow
            from editor_fixture import TOOL_SET_ID

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            tool_id = uuid.uuid4()
            db = fixture.factory()
            db.add(Tool(
                id=str(tool_id), name="Owned catalog lookup",
                description="Read an owned item", tool_type=ToolType.API_REQUEST,
                config={
                    "method": "GET",
                    "url": "https://api.fixture.invalid/items",
                    "parameters": {},
                    "responseMapping": {"amount": "$.amount"},
                    "timeout": 2,
                },
                tool_set_id=uuid.UUID(TOOL_SET_ID), is_active="true",
            ))
            db.commit()
            db.close()
            config = {
                "initial_node": "start",
                "variables": [],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "lookup", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": str(tool_id),
                        "argumentsTemplate": "{}",
                        "responseMapping": {"secret": "$.secret"},
                    }}},
                ],
                "edges": [{"id": "start-lookup", "source": "start", "target": "lookup"}],
            }
            compiled = compile_flow(config, fixture.identity)
            result = await NativeActionRunner(
                compiled, fixture.factory,
            ).execute(compiled.node("lookup"), {})
            assert result.failure_reason == "response_mapping_invalid"
            assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("status_code", [400, 401, 409, 429])
def test_selected_api_request_writes_classify_rejection_and_ambiguity(
    monkeypatch, status_code,
):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        requests = []

        async def controlled_transport(_transport, request):
            requests.append(request)
            return httpx.Response(
                status_code, json={"error": "controlled response"}, request=request,
            )

        async with NativeEffectsFixture() as fixture:
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow
            from editor_fixture import TOOL_SET_ID

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            tool_id = uuid.uuid4()
            db = fixture.factory()
            db.add(Tool(
                id=str(tool_id), name="Create reservation",
                description="Create a reservation", tool_type=ToolType.API_REQUEST,
                config={
                    "method": "POST",
                    "url": "https://api.fixture.invalid/reservations",
                    "parameters": {"name": {"type": "string", "required": True}},
                    "bodyTemplate": '{"name":"{{name}}"}',
                    "responseMapping": {"confirmation": "$.confirmation"},
                    "timeout": 2, "retryCount": 0,
                },
                tool_set_id=uuid.UUID(TOOL_SET_ID), is_active="true",
            ))
            db.commit()
            db.close()
            config = {
                "initial_node": "start",
                "variables": [{"key": "name", "type": "text"}],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Create reservation for {{name}}?",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["name"], "allowEdit": False,
                        },
                    }},
                    {"id": "create", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": str(tool_id),
                        "argumentsTemplate": '{"name":"{{name}}"}',
                        "responseMapping": {"confirmation": "$.confirmation"},
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirm-create", "source": "confirm", "target": "create",
                     "sourceHandle": "confirmed"},
                    {"id": "create-done", "source": "create", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            facts = {"name": "Ari"}
            consent = NativeConfirmation("confirm", 1, '{"name":"Ari"}', ("name",))

            first = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            second = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )

            if status_code in {409, 429}:
                assert first.failure_reason == "effect_outcome_unknown"
                assert second.failure_reason == "effect_outcome_unknown"
                expected_status = "pending"
            else:
                assert first.failure_reason == "tool_operation_rejected"
                assert second == first
                expected_status = "failed"
            assert len(requests) == 1
            db = fixture.factory()
            try:
                claim = db.query(
                    fixture.effect_models["OperationIdempotency"],
                ).one()
                assert claim.status == expected_status
            finally:
                db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status_code", [200, 400, 401, 409, 429])
def test_selected_current_dynamic_operation_reuses_owned_policy_confirmation_and_ledger(
    monkeypatch, status_code,
):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        requests = []

        async def controlled_transport(_transport, request):
            requests.append(request)
            return httpx.Response(
                status_code,
                json={"confirmation": "D-321", "private": "never expose"},
                request=request,
            )

        async with NativeEffectsFixture() as fixture:
            from botelier.models.integration import (
                AccountIntegration, IntegrationAction, IntegrationActionKind,
                IntegrationActionStatus, IntegrationActionVersion, IntegrationStatus,
                IntegrationType,
            )
            from botelier.models.flow_version import FlowVersion, FlowVersionStatus
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
            type_id, action_id, version_id, operation_tool_id = [
                uuid.uuid4() for _ in range(4)
            ]
            operation_id = "create_reservation"
            path = "/reservations"
            endpoint = {
                "id": operation_id, "name": "Create reservation",
                "method": "POST", "path": path, "risk_level": "write",
                "variables": [{"name": "name", "type": "string", "required": True}],
                "response_mapping": {"confirmation": "$.confirmation"},
            }
            policy_mapping = {"confirmation": "$.confirmation"}
            db = fixture.factory()
            integration_type = IntegrationType(
                id=type_id, slug="dynamic-pms", name="Dynamic PMS",
                provider="fixture", auth_type="none", is_enabled=True,
                origin="customer_imported",
            )
            integration_type.set_endpoints([endpoint])
            connection = AccountIntegration(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                integration_type_id=type_id,
                property_id=uuid.UUID(fixture.property_id),
                status=IntegrationStatus.CONNECTED,
                connection_config='{"base_url":"https://api.fixture.invalid"}',
            )
            policy = ConnectionOperationPolicy(
                account_integration_id=connection_id,
                operation_id=operation_id, enabled=True,
                risk_level="write", confirm_required=True,
                approval_required=False, allowed_channels=["voice"],
                test_status="passed", test_passed=True,
                response_mapping=policy_mapping,
            )
            action = IntegrationAction(
                id=action_id, account_id=uuid.UUID(fixture.account_id),
                integration_type_id=type_id, source_endpoint_id=operation_id,
                name="Create reservation", description="Create a reservation",
                slug="create-reservation", kind=IntegrationActionKind.IMPORTED,
                status=IntegrationActionStatus.PUBLISHED,
                published_version_id=version_id, connection_id=connection_id,
                param_ownership={"name": "llm"},
                response_policy=policy.to_dict(),
            )
            version = IntegrationActionVersion(
                id=version_id, action_id=action_id, version_number=1,
                status=IntegrationActionStatus.PUBLISHED,
                config={
                    "integration_id": str(connection_id),
                    "integration_type_id": str(type_id),
                    "endpoint_id": operation_id, "method": "POST", "path": path,
                    "variables": [{"name": "name", "type": "string", "required": True}],
                    "response_mapping": policy_mapping,
                    "risk_level": "write",
                    "request_overrides": {
                        "body_template": '{"name":"{{name}}"}',
                        "headers": {}, "timeout": 2, "retry_count": 0,
                    },
                },
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                output_schema={},
            )
            target = Tool(
                id=str(operation_tool_id), name="Create reservation",
                description="Create a reservation",
                tool_type=ToolType.DYNAMIC_OPERATION,
                config={
                    "integration_action_id": str(action_id),
                    "connection_id": str(connection_id),
                    "operation_id": operation_id,
                },
                tool_set_id=uuid.UUID(TOOL_SET_ID), is_active="true",
            )
            db.add_all([integration_type, connection, policy, action, version, target])
            db.commit()
            db.close()

            config = {
                "initial_node": "start",
                "variables": [{"key": "name", "type": "text"}],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "consent", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Create reservation for {{name}}?",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["name"], "allowEdit": False,
                        },
                    }},
                    {"id": "create", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": str(operation_tool_id),
                        "argumentsTemplate": '{"name":"{{name}}"}',
                        "responseMapping": policy_mapping,
                        "responseProjection": {
                            "fields": [{"variable": "confirmation"}],
                        },
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-consent", "source": "start", "target": "consent"},
                    {"id": "consent-create", "source": "consent", "target": "create",
                     "sourceHandle": "confirmed"},
                    {"id": "create-done", "source": "create", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            facts = {"name": "Ari"}
            consent = NativeConfirmation("consent", 1, '{"name":"Ari"}', ("name",))
            denied = await runner.execute(compiled.node("create"), facts)
            assert denied.failure_reason == "confirmation_required"
            assert requests == []

            preview = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            previewed = await preview.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            assert previewed.failure_reason == "preview_required"
            assert requests == []

            accepted = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            replay = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            if status_code == 200:
                assert accepted.success is True, accepted
                assert accepted.variables == {"confirmation": "D-321"}
                assert replay == accepted
            elif status_code in {409, 429}:
                assert accepted.failure_reason == "effect_outcome_unknown"
                assert replay.failure_reason == "effect_outcome_unknown"
                assert len(requests) == 1
                pending_db = fixture.factory()
                try:
                    claim = pending_db.query(
                        fixture.effect_models["OperationIdempotency"],
                    ).one()
                    assert claim.status == "pending"
                finally:
                    pending_db.close()
                return
            else:
                assert accepted.failure_reason == "tool_operation_rejected"
                assert replay == accepted
                assert len(requests) == 1
                rejected_db = fixture.factory()
                try:
                    claim = rejected_db.query(
                        fixture.effect_models["OperationIdempotency"],
                    ).one()
                    assert claim.status == "failed"
                finally:
                    rejected_db.close()
                return
            assert len(requests) == 1
            assert requests[0].method == "POST"

            db = fixture.factory()
            flow_tool = db.query(Tool).filter(
                Tool.id == fixture.tool_id,
            ).first()
            original_version = db.query(FlowVersion).filter(
                FlowVersion.id == uuid.UUID(fixture.identity.flow_version_id),
            ).first()
            published_again = FlowVersion(
                id=uuid.uuid4(), tool_id=fixture.tool_id, version_number=2,
                status=FlowVersionStatus.PUBLISHED,
                description="New current version while old call is admitted",
                flow_config=original_version.flow_config,
            )
            db.add(published_again)
            flow_tool.published_version_id = published_again.id
            flow_tool.published_version_number = 2
            db.commit()
            db.close()
            retained = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            assert retained == accepted
            assert len(requests) == 1

            db = fixture.factory()
            current_policy = db.query(ConnectionOperationPolicy).filter_by(
                account_integration_id=connection_id,
                operation_id=operation_id,
            ).first()
            current_policy.enabled = False
            db.commit()
            db.close()
            revoked = await runner.execute(
                compiled.node("create"), facts, confirmation=consent,
            )
            assert revoked.failure_reason == "tool_scope_mismatch"
            assert len(requests) == 1

    asyncio.run(scenario())

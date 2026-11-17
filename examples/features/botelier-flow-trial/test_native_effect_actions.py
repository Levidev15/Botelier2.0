import asyncio
import json
import uuid

import httpx


def test_accepted_http_write_with_missing_required_mapping_stays_pending(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            requests = []

            async def controlled_transport(_transport, request):
                requests.append(request)
                return httpx.Response(200, json={}, request=request)

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "amount", "type": "number"},
                    {"key": "reference", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Confirm {{amount}}.",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["amount"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "write", "type": "api_request", "data": {"api": {
                        "apiSource": "custom", "method": "POST",
                        "url": "https://api.fixture.invalid/reserve",
                        "bodyTemplate": '{"amount":{{amount}}}',
                        "responseMapping": {"reference": "$.reference"},
                        "timeout": 2, "retryCount": 0,
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-write", "source": "confirm", "target": "write",
                     "sourceHandle": "confirmed"},
                    {"id": "write-done", "source": "write", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            facts = {"amount": 0}
            consent = NativeConfirmation(
                "confirm", 2, json.dumps(facts), ("amount",),
            )

            denied = await runner.execute(compiled.node("write"), facts)
            assert denied.failure_reason == "confirmation_required"
            assert requests == []
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview_denied = await preview_runner.execute(
                compiled.node("write"), facts,
            )
            assert preview_denied.failure_reason == "confirmation_required"
            preview = await preview_runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            assert preview.failure_reason == "preview_required"
            assert requests == []
            first = await runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            second = await runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            assert first.failure_reason == "effect_outcome_unknown"
            assert second.failure_reason == "effect_outcome_unknown"
            assert len(requests) == 1

    asyncio.run(scenario())


def test_effect_receipts_are_scoped_to_entered_tool_and_published_version(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.flow_version import FlowVersion, FlowVersionStatus
            from botelier.models.operation_idempotency import OperationIdempotency
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow
            from botelier.voice.flows.pilot_contract import PilotIdentity

            child_tool_id = str(uuid.uuid4())
            child_version_id = str(uuid.uuid4())
            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "amount", "type": "number"},
                    {"key": "reference", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Confirm {{amount}}.",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["amount"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "write", "type": "api_request", "data": {"api": {
                        "apiSource": "custom", "method": "POST",
                        "url": "https://api.fixture.invalid/reserve",
                        "bodyTemplate": '{"amount":{{amount}}}',
                        "responseMapping": {"reference": "$.reference"},
                        "timeout": 2, "retryCount": 0,
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-write", "source": "confirm", "target": "write",
                     "sourceHandle": "confirmed"},
                    {"id": "write-done", "source": "write", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            db = fixture.factory()
            db.add(Tool(
                id=child_tool_id, name="Alternate write", description="Scoped test",
                tool_type=ToolType.FLOW, config=config,
                tool_set_id=uuid.UUID("00000000-0000-0000-0000-000000000105"),
                published_version_id=uuid.UUID(child_version_id),
                published_version_number=1,
            ))
            db.add(FlowVersion(
                id=uuid.UUID(child_version_id), tool_id=child_tool_id,
                version_number=1, status=FlowVersionStatus.PUBLISHED,
                flow_config=config,
            ))
            db.commit()
            db.close()

            identity = fixture.identity
            child_identity = PilotIdentity(
                account_id=identity.account_id,
                property_id=identity.property_id,
                tool_id=child_tool_id,
                flow_version_id=child_version_id,
                call_sid=identity.call_sid,
            )
            root_flow = compile_flow(config, identity)
            child_flow = compile_flow(config, child_identity)
            root_runner = NativeActionRunner(root_flow, fixture.factory)
            child_runner = NativeActionRunner(child_flow, fixture.factory)
            requests = []

            async def controlled_transport(_transport, request):
                requests.append(request)
                return httpx.Response(
                    200, json={"reference": "fixture-receipt"}, request=request,
                )

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            facts = {"amount": 12}
            root_consent = NativeConfirmation(
                "confirm", 2, json.dumps(facts), ("amount",),
            )
            child_consent = NativeConfirmation(
                "confirm", 3, json.dumps(facts), ("amount",),
            )
            try:
                root_result = await root_runner.execute(
                    root_flow.node("write"), facts, confirmation=root_consent,
                )
                child_result = await child_runner.execute(
                    child_flow.node("write"), facts, confirmation=child_consent,
                )
                root_replay = await root_runner.execute(
                    root_flow.node("write"), facts, confirmation=root_consent,
                )
                assert root_result.success and child_result.success
                assert root_replay.success
                assert len(requests) == 2
                db = fixture.factory()
                receipts = db.query(OperationIdempotency).all()
                assert len(receipts) == 2
                operations = {row.operation for row in receipts}
                assert len(operations) == 2
                assert all(item.startswith("native:write:") for item in operations)
                assert len({row.idempotency_key for row in receipts}) == 2
                assert all(row.status == "succeeded" for row in receipts)
                db.close()
            finally:
                await root_runner.close()
                await child_runner.close()

    asyncio.run(scenario())


def test_installed_flow_manager_dispatches_actions_through_entered_flow_runner(
    monkeypatch,
):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from native_graph_io import GraphCall
            from botelier.models.flow_version import FlowVersion, FlowVersionStatus
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.services.native_flow_recovery import (
                native_flow_identity, native_flow_source_digest,
            )
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow
            from botelier.voice.flows.pilot_contract import PilotIdentity

            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "query", "type": "text"},
                    {"key": "result", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {
                        "greeting": "", "waitForResponse": False,
                    }},
                    {"id": "query", "type": "collect_slot", "data": {
                        "slot": {"variableKey": "query", "prompt": "Which item?"},
                    }},
                    {"id": "lookup", "type": "api_request", "data": {"api": {
                        "apiSource": "custom", "method": "GET",
                        "url": "https://api.fixture.invalid/lookup?query={{query}}",
                        "responseMapping": {"result": "$.result"},
                        "timeout": 2, "retryCount": 0,
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-query", "source": "start", "target": "query"},
                    {"id": "query-lookup", "source": "query", "target": "lookup"},
                    {"id": "lookup-done", "source": "lookup", "target": "done",
                     "sourceHandle": "success"},
                    {"id": "lookup-error", "source": "lookup", "target": "done",
                     "sourceHandle": "error"},
                ],
            }
            child_tool_id = str(uuid.uuid4())
            child_version_id = str(uuid.uuid4())
            alternate = json.loads(json.dumps(config))
            for node in alternate["nodes"]:
                if node["id"] == "lookup":
                    node["id"] = "alternate_lookup"
            for edge in alternate["edges"]:
                if edge["source"] == "lookup":
                    edge["source"] = "alternate_lookup"
                if edge["target"] == "lookup":
                    edge["target"] = "alternate_lookup"

            db = fixture.factory()
            root_tool = db.query(Tool).filter(
                Tool.id == fixture.identity.tool_id,
            ).first()
            root_version = db.query(FlowVersion).filter(
                FlowVersion.id == uuid.UUID(fixture.identity.flow_version_id),
            ).first()
            root_tool.config = config
            root_version.flow_config = config
            db.add(Tool(
                id=child_tool_id, name="Alternate read",
                description="Scoped installed SDK test",
                tool_type=ToolType.FLOW, config=alternate,
                tool_set_id=uuid.UUID("00000000-0000-0000-0000-000000000105"),
                published_version_id=uuid.UUID(child_version_id),
                published_version_number=1,
            ))
            db.add(FlowVersion(
                id=uuid.UUID(child_version_id), tool_id=child_tool_id,
                version_number=1, status=FlowVersionStatus.PUBLISHED,
                flow_config=alternate,
            ))
            db.commit()
            db.close()

            root = compile_flow(config, fixture.identity)
            child = compile_flow(alternate, PilotIdentity(
                account_id=fixture.identity.account_id,
                property_id=fixture.identity.property_id,
                tool_id=child_tool_id, flow_version_id=child_version_id,
                call_sid=fixture.identity.call_sid,
            ))
            root_runner = NativeActionRunner(root, fixture.factory)
            child_runner = NativeActionRunner(child, fixture.factory)
            runners = {
                fixture.identity.tool_id: root_runner,
                child_tool_id: child_runner,
            }
            available_flows = {
                fixture.identity.tool_id: {
                    "compiled": root, "name": "Root fixture", "description": "Root",
                },
                child_tool_id: {
                    "compiled": child, "name": "Alternate fixture",
                    "description": "Child",
                },
            }
            requests = []

            async def controlled_transport(_transport, request):
                requests.append(request)
                return httpx.Response(
                    200, json={"result": "fixture-result"}, request=request,
                )

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            call = GraphCall(
                root, available_flows=available_flows, action_runners=runners,
            )

            async def select(flow_id):
                selector = next(
                    schema for schema in call.worker.tools.values()
                    if "select_flow_" in schema.name
                )
                call.user_turn("Choose the currently assigned workflow.")
                return await call.invoke_schema(selector, {"tool_id": flow_id})

            async def enter_query(value):
                schema = next(
                    schema for schema in call.worker.tools.values()
                    if schema.name.startswith("native_query_")
                )
                call.user_turn(value)
                return await call.invoke_schema(schema, {"query": value})

            recovered = None
            try:
                await call.adapter.start()
                result = await select(child_tool_id)
                assert result["status"] == "selected"
                assert call.adapter.compiled is child
                assert call.adapter.execute_action.__self__ is child_runner
                await enter_query("alternate")
                assert len(requests) == 1
                assert "query=alternate" in str(requests[0].url)
                assert call.adapter.compiled is root
                assert call.adapter.execute_action.__self__ is root_runner

                result = await select(fixture.identity.tool_id)
                assert result["status"] == "selected"
                await enter_query("standard")
                assert len(requests) == 2
                assert "query=standard" in str(requests[1].url)
                assert call.adapter.compiled is root
                assert call.adapter.execute_action.__self__ is root_runner

                snapshot = {
                    "schema_version": 1,
                    "revision": 8,
                    "root": native_flow_identity(root),
                    "source_digest": native_flow_source_digest(root),
                    "active": {
                        **native_flow_identity(child),
                        "source_digest": native_flow_source_digest(child),
                    },
                    "current_node_id": "query",
                    "node_revision": 2,
                    "total_steps": 2,
                    "state": "active",
                    "catalog_active": True,
                    "awaiting_flow_choice": False,
                    "facts": {"query": "alternate"},
                    "caller_facts": {"query": "alternate"},
                    "fact_provenance": {"query": "caller"},
                    "llm_data": {},
                    "effect": None,
                }
                recovered = GraphCall(
                    root, available_flows=available_flows,
                    action_runners=runners, recovery_snapshot=snapshot,
                )
                await recovered.adapter.start()
                assert recovered.adapter.compiled is child
                assert recovered.adapter.execute_action.__self__ is child_runner
                assert len(requests) == 2
            finally:
                if recovered is not None:
                    await recovered.adapter.close()
                await call.adapter.close()
                await root_runner.close()
                await child_runner.close()

    asyncio.run(scenario())

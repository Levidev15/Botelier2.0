"""Installed flow-manager dispatch must stay bound to the entered flow."""

import asyncio

import httpx
import pytest

from lifecycle_io import CALL_SID
from native_dev_voice_io import (
    ACCOUNT, ALT_TOOL_ID, ALT_VERSION_ID, NativeDevRecords, PROPERTY, TOOL_ID,
    VERSION_ID,
)


@pytest.mark.parametrize("child_action_id", ["lookup", "alternate_lookup"])
def test_installed_flow_manager_dispatches_actions_through_entered_flow_runner(
    monkeypatch, child_action_id,
):
    async def scenario():
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport
        from botelier.services.native_flow_recovery import (
            native_flow_identity, native_flow_source_digest,
        )
        from botelier.voice.flows.native_actions import NativeActionRunner
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity
        from native_graph_io import GraphCall

        records = NativeDevRecords(extra_published_flow=True)
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
        alternate = {
            **config,
            "nodes": [dict(node) for node in config["nodes"]],
            "edges": [dict(edge) for edge in config["edges"]],
        }
        if child_action_id != "lookup":
            for node in alternate["nodes"]:
                if node["id"] == "lookup":
                    node["id"] = child_action_id
            for edge in alternate["edges"]:
                if edge["source"] == "lookup":
                    edge["source"] = child_action_id
                if edge["target"] == "lookup":
                    edge["target"] = child_action_id

        records.rows["Tool"][0].config = config
        records.rows["Tool"][1].config = alternate
        records.rows["FlowVersion"].flow_config = config
        records.rows["AdditionalFlowVersions"][0].flow_config = alternate
        root = compile_flow(config, PilotIdentity(
            account_id=ACCOUNT, property_id=PROPERTY, tool_id=TOOL_ID,
            flow_version_id=VERSION_ID, call_sid=CALL_SID,
        ))
        child = compile_flow(alternate, PilotIdentity(
            account_id=ACCOUNT, property_id=PROPERTY, tool_id=ALT_TOOL_ID,
            flow_version_id=ALT_VERSION_ID, call_sid=CALL_SID,
        ))
        root_runner = NativeActionRunner(root, records.session)
        child_runner = NativeActionRunner(child, records.session)
        runners = {TOOL_ID: root_runner, ALT_TOOL_ID: child_runner}
        available_flows = {
            TOOL_ID: {
                "compiled": root, "name": "Root fixture", "description": "Root",
            },
            ALT_TOOL_ID: {
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
            result = await select(ALT_TOOL_ID)
            assert result["status"] == "selected"
            assert call.adapter.compiled is child
            assert call.adapter.execute_action.__self__ is child_runner
            await enter_query("alternate")
            assert len(requests) == 1
            assert "query=alternate" in str(requests[0].url)
            assert call.adapter.compiled is root
            assert call.adapter.execute_action.__self__ is root_runner

            result = await select(TOOL_ID)
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

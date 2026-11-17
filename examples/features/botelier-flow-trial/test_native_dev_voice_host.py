"""Exercise explicit native-dev selection through the real voice coordinator."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from lifecycle_io import CALL_SID, GREETING, PRIVATE_PROMPT
from native_dev_voice_io import (
    ALT_TOOL_ID, NativeDevVoiceCall, REPLACEMENT_VERSION_ID, TOOL_ID, VERSION_ID,
)
from node_contract_io import API_URL, PRESENTATION, PROPERTY, speech, tool_delta
from pilot_io import PilotProviders


@pytest.mark.parametrize(
    "environment,toggle,enabled",
    [
        (None, None, False),
        ("production", "1", False),
        ("Development", "1", False),
        ("development", "true", False),
        ("development", "1", True),
    ],
)
def test_native_development_policy_requires_exact_server_and_opt_in_values(
    environment, toggle, enabled,
):
    from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy

    policy = NativeFlowDevPolicy(environment, toggle)
    assert policy.enabled is enabled


def test_application_policy_reads_only_the_two_exact_environment_gates(monkeypatch):
    from botelier.voice.call_handler import CallHandler

    monkeypatch.delenv("BOTELIER_ENV", raising=False)
    monkeypatch.delenv("BOTELIER_NATIVE_FLOWS_DEV", raising=False)
    assert not CallHandler().native_flow_dev_policy.enabled

    monkeypatch.setenv("BOTELIER_ENV", "development")
    monkeypatch.setenv("BOTELIER_NATIVE_FLOWS_DEV", "1")
    assert CallHandler().native_flow_dev_policy.enabled

    monkeypatch.setenv("BOTELIER_ENV", "production")
    assert not CallHandler().native_flow_dev_policy.enabled


def test_explicit_native_selection_runs_on_real_worker_after_greeting_and_without_executor():
    async def scenario():
        async with NativeDevVoiceCall(native_enabled=True) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.native_adapter = adapter
            call.adapter = adapter
            assert adapter.worker is call.created[1]
            assert adapter.manager._llm is call.created[2]
            assert adapter.context_aggregator is call.created[3]
            assert not adapter._started

            await call.wait_until(lambda: (
                call.records.call.ai_greeting_completed
                and adapter._started
                and "Which fixture?" in speech(call)
            ))
            assert speech(call)[0] == GREETING
            assert not call.handler.call_mappers

            await call.providers.user_turn("Check the standard fixture.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and call.adapter.manager.current_node == "choice"
                and not call.created[5]._bot_speaking
            ))
            assert call.adapter.compiled.identity.property_id == PROPERTY
            assert call.adapter.compiled.identity.tool_id == TOOL_ID
            assert call.adapter.compiled.identity.flow_version_id == VERSION_ID
            assert len(call.providers.business_requests) == 1
            assert str(call.providers.business_requests[0].url) == (
                API_URL + "?query=standard"
            )
            assert call.handler.call_mappers == {}

            model_requests = [
                body for body in call.providers.requests if body.get("stream")
            ]
            system_text = "\n".join(
                message.get("content", "")
                for message in model_requests[0]["messages"]
                if message.get("role") == "system"
            )
            assert PRIVATE_PROMPT in system_text
            assert PRIVATE_PROMPT not in " ".join(speech(call))

            stored = call.records.rows["FlowSession"][0].collected_slots["native_flow"]
            assert stored["current_node_id"] == "choice"
            assert stored["caller_facts"] == {"query": "standard"}
            assert stored["fact_provenance"]["query"] == "caller"
            assert stored["root"]["flow_version_id"] == VERSION_ID
            records = call.records
            await call.finish("graceful_end")
            assert adapter.closed
            call.assert_clean()

        from botelier.models.flow_version import FlowVersionStatus

        replacement = deepcopy(records.rows["FlowVersion"].flow_config)
        replacement["nodes"][1]["data"]["slot"]["prompt"] = (
            "This is a newer published source and must not replace recovery."
        )
        records.rows["Tool"][0].published_version_id = REPLACEMENT_VERSION_ID
        records.rows["AdditionalFlowVersions"].append(SimpleNamespace(
            id=REPLACEMENT_VERSION_ID,
            tool_id=TOOL_ID,
            status=FlowVersionStatus.PUBLISHED,
            version_number=2,
            flow_config=replacement,
        ))
        async with NativeDevVoiceCall(records=records) as recovered:
            await recovered.wait_until(lambda: (
                recovered.started.is_set()
                and recovered.handler.native_flow_hosts[CALL_SID]._started
                and recovered.handler.native_flow_hosts[CALL_SID].manager.current_node
                == "choice"
                and "Which option?" in speech(recovered)
            ))
            resumed = recovered.handler.native_flow_hosts[CALL_SID]
            assert resumed.compiled.identity.flow_version_id == VERSION_ID
            assert resumed.facts["query"] == "standard"
            assert "rooms" in resumed.facts
            assert recovered.providers.business_requests == []
            await recovered.finish("graceful_end")
            recovered.assert_clean()

    asyncio.run(scenario())


def test_prewarmed_call_uses_pinned_published_graph_not_tool_snapshot():
    async def scenario():
        async with NativeDevVoiceCall(prewarmed=True) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.adapter = adapter
            query = adapter.compiled.node("query")
            assert query.node_id == "query"
            assert query.data()["slot"]["prompt"] == "Which fixture?"
            assert adapter.compiled.identity.flow_version_id == VERSION_ID
            assert not call.handler.call_mappers

            await call.wait_until(lambda: (
                adapter._started and "Which fixture?" in speech(call)
            ))
            await call.providers.user_turn("Check the standard fixture.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and len(call.providers.business_requests) == 1
                and adapter.manager.current_node == "choice"
            ))
            assert adapter.manager.current_node == "choice"
            assert call.handler.call_mappers == {}
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


def test_actual_voice_selects_the_explicit_published_flow_from_multiple_assignments():
    async def scenario():
        from botelier.voice.flows.native_adapter import NativeFlowAdapter

        providers = PilotProviders([
            {
                "tool_calls": [{
                    "index": 0, "id": "multi-flow-query", "type": "function",
                    "function": {
                        "name": "collect_query",
                        "arguments": '{"query":"standard"}',
                    },
                }],
            },
            "The selected fixture is ready.",
        ])
        async with NativeDevVoiceCall(
            extra_tool=True, with_global_prompt=True, extra_global_tool=True,
            escalation=True, with_mcp=True, providers=providers,
        ) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            assert isinstance(adapter, NativeFlowAdapter)
            assert adapter.compiled.identity.tool_id == TOOL_ID
            assert adapter.compiled.identity.flow_version_id == VERSION_ID
            await call.wait_until(lambda: (
                adapter._started and "Which fixture?" in speech(call)
            ))
            await call.providers.user_turn("Check the standard fixture.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and len(call.providers.business_requests) == 1
                and adapter.manager.current_node == "choice"
            ))
            assert adapter.manager.current_node == "choice"
            assert len(call.providers.business_requests) == 1
            assert any(
                message.get("content")
                == "Keep the caller's requested availability constraints intact."
                for request in call.providers.requests
                for message in request.get("messages", [])
            )
            model_tool_names = {
                item["function"]["name"]
                for request in call.providers.requests
                for item in request.get("tools", [])
                if item.get("type") == "function"
            }
            assert {
                "end_call_fixture", "request_human", "lookup",
            } <= model_tool_names
            assert "reserve" not in model_tool_names
            assert call.handler.call_mappers[CALL_SID].get_flow_executors() == []
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


def test_native_root_selects_and_returns_between_published_assigned_flows():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_select_flow", {"tool_id": ALT_TOOL_ID}),
            tool_delta("collect_query", {"query": "alternate"}),
            tool_delta("collect_choice", {"choice": "Standard"}),
            "Would you like another task, or should I end the call?",
        ])
        async with NativeDevVoiceCall(
            extra_published_flow=True, providers=providers,
        ) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            await call.wait_until(lambda: (
                adapter._started and adapter.manager.current_node == "start"
            ))
            root_runner = adapter._action_runners[TOOL_ID]
            child_runner = adapter._action_runners[ALT_TOOL_ID]
            assert adapter.execute_action.__self__ is root_runner
            assert root_runner.compiled.node("lookup").node_id == (
                child_runner.compiled.node("lookup").node_id
            )
            await call.providers.user_turn("Use the fixture support workflow.")
            await call.wait_until(lambda: (
                adapter.compiled.identity.tool_id == ALT_TOOL_ID
                and "Which alternate fixture?" in speech(call)
            ))
            assert adapter._catalog_active is True
            assert adapter.manager.current_node == "query"
            assert adapter.execute_action.__self__ is child_runner
            await call.providers.user_turn("Find alternate.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and len(call.providers.business_requests) == 1
            ))
            assert "query=alternate" in str(call.providers.business_requests[0].url)
            await call.providers.user_turn("Select Standard.")
            await call.wait_until(lambda: (
                adapter._awaiting_flow_choice
                and adapter.compiled.identity.tool_id == TOOL_ID
                and "Would you like another task, or should I end the call?"
                in speech(call)
            ))
            assert adapter._catalog_active is False
            assert adapter.execute_action.__self__ is root_runner
            assert adapter.facts == {
                "query": "alternate",
                "choice": "Standard",
            }
            root_selection = next(
                function for function in adapter.manager._global_functions
                if function.name == "native_exit_call"
            )
            assert root_selection.name == "native_exit_call"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_prewarmed_native_ownership_rejection_does_not_fall_back_to_legacy():
    async def scenario():
        async with NativeDevVoiceCall(
            prewarmed=True, wrong_ownership="property",
        ) as call:
            await asyncio.wait_for(asyncio.shield(call.run_task), timeout=4.0)
            call.assert_rejected_before_pipeline("native_dev_ownership")
            assert not call.providers.requests

    asyncio.run(scenario())


def test_prewarmed_native_call_revalidates_and_exposes_only_readonly_mcp_globals():
    async def scenario():
        async with NativeDevVoiceCall(prewarmed=True, with_mcp=True) as call:
            await call.wait_until(lambda: (
                call.started.is_set()
                and call.handler.native_flow_hosts[CALL_SID]._started
            ))
            adapter = call.handler.native_flow_hosts[CALL_SID]
            await call.providers.user_turn("Check the standard fixture.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and len(call.providers.business_requests) == 1
                and adapter.manager.current_node == "choice"
            ))
            model_tool_names = {
                item["function"]["name"]
                for request in call.providers.requests
                for item in request.get("tools", [])
                if item.get("type") == "function"
            }
            assert "lookup" in model_tool_names
            assert "reserve" not in model_tool_names
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_native_voice_executes_only_currently_authorized_global_readonly_mcp_tool():
    async def scenario():
        providers = PilotProviders([
            tool_delta("lookup", {}),
            "The fixture lookup is preview-only.",
        ])
        async with NativeDevVoiceCall(
            with_mcp=True, providers=providers,
        ) as call:
            await call.wait_until(lambda: (
                call.started.is_set()
                and call.handler.native_flow_hosts[CALL_SID]._started
            ))
            await call.providers.user_turn("Read the fixture lookup.")
            await call.wait_until(lambda: (
                bool(call.mcp_calls)
                and "The fixture lookup is preview-only." in speech(call)
            ))
            assert call.mcp_calls == [("lookup", {})]
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_native_start_is_independent_of_missing_call_log_and_keeps_native_tools():
    async def scenario():
        async with NativeDevVoiceCall(
            prewarmed=True, missing_call_log=True,
        ) as call:
            await call.wait_until(lambda: call.started.is_set())
            assert call.records.rows["CallLog"] is None
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.adapter = adapter
            await call.wait_until(lambda: (
                adapter._started and "Which fixture?" in speech(call)
            ))
            assert speech(call)[0] == GREETING
            await call.providers.user_turn("Check the standard fixture.")
            await call.wait_until(lambda: (
                PRESENTATION in speech(call)
                and len(call.providers.business_requests) == 1
                and adapter.manager.current_node == "choice"
            ))
            assert adapter.manager.current_node == "choice"
            await call.finish("graceful_end")
            assert adapter.closed
            call.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "resources,expected_code",
    [
        ({"bad_contract": True}, "definition_field"),
        ({"wrong_ownership": "tool_set"}, "native_dev_ownership"),
        ({"wrong_ownership": "property"}, "native_dev_ownership"),
        ({"wrong_ownership": "tool"}, "native_dev_ownership"),
        ({"missing_version": True}, "native_dev_published_version"),
        ({"unpublished_version": True}, "native_dev_published_version"),
        ({"wrong_selection": True}, "native_dev_resources"),
    ],
)
def test_unsupported_native_resources_and_graphs_fail_before_worker_creation(
    resources, expected_code,
):
    async def scenario():
        async with NativeDevVoiceCall(**resources) as call:
            await call.run_task
            call.assert_rejected_before_pipeline(expected_code)
            assert not call.providers.requests
            assert not call.providers.business_requests

    asyncio.run(scenario())


def test_greeting_hangup_before_native_start_closes_call_owned_adapter():
    async def scenario():
        providers = PilotProviders([
            {"tool_calls": []},
        ], hold_tts_turn=1)
        async with NativeDevVoiceCall(
            native_enabled=True, providers=providers,
        ) as call:
            await call.wait_until(lambda: (
                call.started.is_set()
                and any(item.get("type") == "Speak" for item in providers.tts.sent)
            ))
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.native_adapter = adapter
            assert not adapter._started
            await call.finish("caller_hangup")
            assert adapter.closed
            assert not adapter._started
            call.assert_clean()

    asyncio.run(scenario())


def test_hangup_cancels_native_action_and_disposes_adapter_and_session():
    async def scenario():
        providers = PilotProviders([
            {"tool_calls": [{
                "index": 0, "id": "native-dev-call", "type": "function",
                "function": {
                    "name": "collect_query",
                    "arguments": '{"query":"standard"}',
                },
            }]},
        ], status="hold")
        async with NativeDevVoiceCall(
            native_enabled=True, providers=providers,
        ) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.adapter = adapter
            await call.wait_until(lambda: adapter._started)
            await providers.user_turn("Check the standard fixture.")
            await asyncio.wait_for(providers.business_started.wait(), timeout=4.0)
            await call.finish("caller_hangup")
            assert providers.business_cancelled
            assert adapter.closed
            assert all(session.closed for session in call.actions.sessions)
            call.assert_clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("prewarmed", [False, True])
def test_default_off_and_production_policy_keep_the_legacy_flow_controller(prewarmed):
    async def scenario():
        from botelier.voice.call_handler import CallHandler
        from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy

        for policy in (
            NativeFlowDevPolicy(None, None),
            NativeFlowDevPolicy("production", "1"),
        ):
            async with NativeDevVoiceCall(
                native_enabled=False, prewarmed=prewarmed,
                handler=CallHandler(native_flow_dev_policy=policy),
            ) as call:
                await call.wait_until(lambda: call.started.is_set())
                assert CALL_SID not in call.handler.native_flow_hosts
                assert call.handler.call_mappers[CALL_SID].get_flow_executors()
                await call.finish("graceful_end")
                call.assert_clean()

    asyncio.run(scenario())

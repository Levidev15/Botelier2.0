"""End-to-end HTTP checks for the actual simulator router and native text host."""

import asyncio
from unittest.mock import patch

import pytest

from native_simulation_io import NativeSimulationAPIHarness
from node_contract_io import API_URL, ACCOUNT, PROPERTY, tool_delta
from native_dev_voice_io import TOOL_ID, VERSION_ID


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


def error_code(response):
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else detail


def test_native_http_flow_uses_real_owned_published_graph_and_native_text_worker():
    async def scenario():
        async with NativeSimulationAPIHarness(
            replies=[
                tool_delta("collect_query", {"query": "standard"}, "http-query"),
                tool_delta("collect_choice", {"choice": "standard"}, "http-choice"),
                "Your choice is paused for this pilot.",
            ],
        ) as harness:
            api = harness.api
            with patch.object(
                api.FlowExecutor,
                "__init__",
                side_effect=AssertionError("native request fell through to FlowExecutor"),
            ):
                started = await harness.start()

            assert started.status_code == 200, started.text
            start_body = started.json()
            session = harness.active_sessions[-1]
            host = session.host
            assert session.engine == "native_pilot"
            assert session.owner_user_id == str(harness.records.admin.id)
            assert session.account_id == ACCOUNT
            assert harness.records.tool.config == {}
            assert start_body["runtime"] == {
                "engine": "native_pilot",
                "source": "published",
                "tool_id": TOOL_ID,
                "assistant_id": str(harness.records.assistant.id),
                "account_id": ACCOUNT,
                "property_id": PROPERTY,
                "flow_version_id": VERSION_ID,
                "version_number": 1,
                "llm_provider": harness.records.assistant.llm_provider,
                "llm_model": harness.records.assistant.llm_model,
            }
            assert start_body["state"]["current_node"] == "query"
            assert start_body["state"]["pending_slot"] == "query"
            assert start_body["greeting"]
            assert all(message["role"] == "assistant" for message in start_body["messages"])
            assert "Private fixture instructions" not in started.text
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []

            from botelier.voice.flows.native_text_host import NativeTextHost
            from botelier.voice.flows.pilot_adapter import NativePilotAdapter
            from pipecat.flows.manager import FlowManager
            from pipecat.pipeline.worker import PipelineWorker

            assert isinstance(host, NativeTextHost)
            assert isinstance(host.adapter, NativePilotAdapter)
            assert isinstance(host.adapter.manager, FlowManager)
            assert isinstance(host._worker, PipelineWorker)
            processor_names = {
                type(processor).__name__ for processor in host._pipeline_processors
            }
            assert not any("STT" in name or "TTS" in name for name in processor_names)
            initial_tools = {
                tool.name for tool in host.context.tools.standard_tools
            }
            assert len(initial_tools) == 1
            assert next(iter(initial_tools)).startswith("pilot_collect_query_")

            harness.events.clear()
            queried = await harness.message(
                start_body["session_id"],
                "Check the standard fixture.",
            )
            assert queried.status_code == 200, queried.text
            query_body = queried.json()
            assert isinstance(query_body["function_called"], str)
            assert query_body["function_called"].startswith("pilot_collect_query_")
            assert query_body["function_result"]["data"] == {
                "rooms": [{"name": "Standard", "price": 0}],
                "price": 0,
            }
            assert query_body["runtime"] == start_body["runtime"]
            assert query_body["suggested_functions"] == []
            assert query_body["error"] is None
            assert len(harness.fixture.providers.business_requests) == 1
            business_request = harness.fixture.providers.business_requests[0]
            assert business_request.method == "GET"
            assert str(business_request.url) == API_URL + "?query=standard"
            assert query_body["state"]["current_node"] == "choice"
            assert query_body["state"]["pending_slot"] == "choice"
            assert all(message["role"] == "assistant" for message in query_body["messages"])
            assert host.snapshot()["current_node"] == "choice"

            provider_index = next(
                index for index, event in enumerate(harness.events)
                if event[0] == "provider"
            )
            db_close_index = next(
                index for index, event in enumerate(harness.events)
                if event[0] == "db.close"
            )
            assert db_close_index < provider_index, (
                "request DB must close before provider/action work begins"
            )
            assert not any(
                event[0] == "db.query" for event in harness.events[provider_index + 1:]
            )

            current_tools = {
                tool.name for tool in host.context.tools.standard_tools
            }
            assert len(current_tools) == 1
            assert next(iter(current_tools)).startswith("pilot_collect_choice_")

            # NativeSimulationSession enforces its production minimum interval.
            await asyncio.sleep(1.05)
            paused = await harness.message(
                start_body["session_id"],
                "I choose the standard option.",
            )
            assert paused.status_code == 200, paused.text
            paused_body = paused.json()
            assert paused_body["runtime"] == start_body["runtime"]
            assert isinstance(paused_body["function_called"], str)
            assert paused_body["function_called"].startswith("pilot_collect_choice_")
            assert paused_body["function_result"]["outcome"] == "paused"
            assert paused_body["function_result"]["booking_completed"] is False
            assert paused_body["state"] == host.snapshot()
            assert paused_body["state"]["is_complete"] is False
            assert paused_body["state"]["progress"] == {
                "collected": 2, "total": 2, "percentage": 100,
            }
            assert len(harness.fixture.providers.business_requests) == 1
            model_requests = [
                request for request in harness.fixture.providers.requests
                if request.get("stream")
            ]
            assert len(model_requests) == 3, (
                "final paused collection must include the SDK follow-up model cycle"
            )
            for model_request in model_requests:
                assert model_request["model"] == harness.records.assistant.llm_model
                assert model_request["temperature"] == harness.records.assistant.temperature
                assert model_request["max_completion_tokens"] == harness.records.assistant.max_tokens
            assert harness.fixture.actions.writes

            state = await harness.state(start_body["session_id"])
            assert state.status_code == 200, state.text
            assert state.json()["state"] == host.snapshot()

            deleted = await harness.delete(start_body["session_id"])
            assert deleted.status_code == 200, deleted.text
            assert host.closed is True
            assert session.is_ended is True
            assert harness.registry.active_count == 0

    run(scenario)


@pytest.mark.parametrize("source", ["draft", "unsaved"])
def test_native_http_rejects_nonpublished_sources_before_provider_work(source):
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            response = await harness.start(source=source)
            assert response.status_code == 400, response.text
            assert error_code(response) == "native_simulation_published_source_required"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert harness.registry is None or harness.registry.active_count == 0
            assert harness.registry is None or harness.registry.pending_count == 0
    run(scenario)


def test_native_http_rejects_stale_version_before_provider_work():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            response = await harness.start(source_version=2)
            assert response.status_code == 409, response.text
            assert error_code(response) == "native_simulation_version_changed"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert harness.registry is None or harness.registry.active_count == 0
            assert harness.registry is None or harness.registry.pending_count == 0
    run(scenario)


@pytest.mark.parametrize("source_version", [True, "1"])
def test_native_http_rejects_coerced_version_values_at_request_validation(source_version):
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            response = await harness.start(source_version=source_version)
            assert response.status_code == 422, response.text
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert harness.registry is None or harness.registry.active_count == 0
    run(scenario)


def test_native_http_requires_explicit_assistant_and_refuses_unsupported_globals():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            payload = harness.start_payload()
            payload.pop("assistant_id")
            missing_assistant = await harness.client.post(
                "/api/simulate/start",
                json=payload,
                headers=harness.headers(harness.records.admin),
            )
            assert missing_assistant.status_code == 400, missing_assistant.text
            assert error_code(missing_assistant) == "native_dev_selection"
            assert harness.fixture.providers.requests == []

        async with NativeSimulationAPIHarness(bad_contract=True) as harness:
            unsupported = await harness.start()
            assert unsupported.status_code == 400, unsupported.text
            assert error_code(unsupported) == "native_simulation_flow_unsupported"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert harness.registry is None or harness.registry.active_count == 0
            assert harness.registry is None or harness.registry.pending_count == 0
    run(scenario)


def test_native_http_host_start_failure_releases_pending_reservation():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            # NativeTextHost's real greeting-size admission refuses before
            # pipeline/provider startup, after the API has reserved its session.
            harness.records.assistant.first_message = "g" * 8_001
            response = await harness.start()
            assert response.status_code == 400, response.text
            assert error_code(response) == "native_simulation_failed"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert harness.registry.pending_count == 0
            assert harness.registry.active_count == 0
    run(scenario)


def test_native_http_production_gate_and_unverified_provider_fail_closed():
    async def scenario():
        async with NativeSimulationAPIHarness(environment="production") as harness:
            disabled = await harness.start()
            assert disabled.status_code == 403, disabled.text
            assert error_code(disabled) == "native_dev_disabled"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []

        async with NativeSimulationAPIHarness(
            environment="development", native_enabled="0",
        ) as harness:
            disabled_opt_in = await harness.start()
            assert disabled_opt_in.status_code == 403, disabled_opt_in.text
            assert error_code(disabled_opt_in) == "native_dev_disabled"
            assert harness.fixture.providers.requests == []

        async with NativeSimulationAPIHarness() as harness:
            harness.records.assistant.llm_provider = "google_gemini"
            response = await harness.start()
            assert response.status_code == 400, response.text
            assert error_code(response) == "native_simulation_provider_unsupported"
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
    run(scenario)


def test_native_http_auth_and_owner_isolation_are_checked_before_host_work():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            anonymous = await harness.client.post(
                "/api/simulate/start",
                json=harness.start_payload(),
            )
            assert anonymous.status_code == 401

            denied = await harness.start(user=harness.records.denied_user)
            assert denied.status_code == 403, denied.text
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []

            started = await harness.start(user=harness.records.admin)
            assert started.status_code == 200, started.text
            session_id = started.json()["session_id"]
            host = harness.active_sessions[-1].host
            for response in (
                await harness.state(session_id, user=harness.records.other_admin),
                await harness.message(
                    session_id, "private history probe",
                    user=harness.records.other_admin,
                ),
                await harness.delete(session_id, user=harness.records.other_admin),
            ):
                assert response.status_code == 404, response.text
                assert "Hello, this is the offline fixture." not in response.text
            assert harness.fixture.providers.requests == []
            assert harness.fixture.providers.business_requests == []
            assert host.context.get_messages()[-1]["role"] != "user"
            deleted = await harness.delete(session_id, user=harness.records.admin)
            assert deleted.status_code == 200
    run(scenario)


@pytest.mark.parametrize(
    "injection",
    [
        {"function_call": "collect_query"},
        {"function_args": {"query": "forged"}},
    ],
)
def test_native_http_rejects_manual_function_injection_without_a_model_turn(injection):
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            started = await harness.start()
            assert started.status_code == 200, started.text
            session_id = started.json()["session_id"]
            session = harness.active_sessions[-1]
            before = session.host.context.get_messages()
            response = await harness.message(session_id, "hello", **injection)
            assert response.status_code == 400, response.text
            assert error_code(response) == "native_simulation_manual_calls_disabled"
            assert harness.fixture.providers.requests == []
            assert session.host.context.get_messages() == before
            await harness.delete(session_id)
    run(scenario)


def test_native_http_lifespan_closes_live_worker_and_default_engine_remains_legacy():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            default_engine = harness.api.StartSimulationRequest(
                tool_id=TOOL_ID,
                assistant_id=str(harness.records.assistant.id),
            ).engine
            assert default_engine == "legacy"
            started = await harness.start()
            assert started.status_code == 200, started.text
            session = harness.active_sessions[-1]
            assert harness.registry.active_count == 1
        assert harness.shutdown_active_count == 0
        assert session.host.closed is True
        assert session.is_ended is True
    run(scenario)


def test_legacy_start_without_engine_keeps_the_existing_flow_executor_path():
    async def scenario():
        async with NativeSimulationAPIHarness(
            stale_tool_config=False,
        ) as harness:
            original_init = harness.api.FlowExecutor.__init__
            executor_calls = []

            def observe_executor(instance, *args, **kwargs):
                executor_calls.append(instance)
                return original_init(instance, *args, **kwargs)

            with patch.object(harness.api.FlowExecutor, "__init__", observe_executor):
                response = await harness.client.post(
                    "/api/simulate/start",
                    json={
                        "tool_id": harness.records.tool.id,
                        "assistant_id": str(harness.records.assistant.id),
                    },
                    headers=harness.headers(harness.records.admin),
                )
            assert response.status_code == 200, response.text
            assert len(executor_calls) == 1
            assert response.json().get("runtime") is None
            await harness.delete(response.json()["session_id"])
    run(scenario)


def test_native_api_route_and_schema_are_actual_candidate_sources():
    async def scenario():
        async with NativeSimulationAPIHarness() as harness:
            assert harness.api.StartSimulationRequest.model_fields["engine"].default == "legacy"
            assert harness.api.StartSimulationRequest.model_fields["source"].default is None
            assert harness.api.StartSimulationRequest.model_fields["source_version"].default is None
    run(scenario)


def test_native_http_uses_backend_source_when_trial_files_are_mounted_separately():
    async def scenario():
        import native_simulation_io

        with patch.object(
            native_simulation_io, "__file__",
            "/ci/examples/features/botelier-flow-trial/native_simulation_io.py",
        ):
            async with NativeSimulationAPIHarness() as harness:
                response = await harness.start()
                assert response.status_code == 200, response.text
                assert response.json()["runtime"]["engine"] == "native_pilot"
                await harness.delete(response.json()["session_id"])
    run(scenario)


def test_native_http_harness_still_rejects_a_counterfeit_router_source():
    async def scenario():
        import botelier.api.simulation as actual_api

        harness = NativeSimulationAPIHarness()
        with patch.object(
            actual_api, "__file__", "/not-approved/botelier/api/simulation.py",
        ):
            try:
                with pytest.raises(RuntimeError, match="actual simulation API route"):
                    await harness.__aenter__()
            finally:
                await harness.__aexit__(None, None, None)
    run(scenario)

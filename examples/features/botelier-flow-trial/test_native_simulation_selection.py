"""Native Test Lab source admission; no server, providers or customer storage."""

import asyncio
import importlib.util
from types import SimpleNamespace

import pytest

from application_support import load_function_mapper


def selection_case(**record_options):
    load_function_mapper()
    from native_dev_voice_io import NativeDevRecords, TOOL_ID
    from node_contract_io import ACCOUNT
    from botelier.services import native_simulation
    from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy

    records = NativeDevRecords(**record_options)
    records.rows["FlowVersion"].version_number = 1
    request = SimpleNamespace(
        engine="native_pilot", source="published", source_version=1,
        tool_id=TOOL_ID, assistant_id=str(records.assistant.id),
    )
    arguments = {
        "request": request,
        "assistant": records.assistant,
        "tool": records.rows["Tool"][0],
        "db": records.session(),
        "account_id": ACCOUNT,
        "session_id": "offline-native-simulation",
        "policy": NativeFlowDevPolicy("development", "1"),
    }
    return native_simulation, records, arguments


def test_native_simulator_uses_the_owned_published_graph_not_stale_tool_config():
    async def scenario():
        module, records, arguments = selection_case()
        from native_dev_voice_io import TOOL_ID, VERSION_ID
        from node_contract_io import ACCOUNT, PROPERTY

        records.rows["Tool"][0].config = {"nodes": [], "globalPrompt": "STALE"}
        records.assistant.temperature = 0
        plan = await module.prepare_native_simulation(**arguments)
        query = plan.compiled.node("query")
        assert query.node_id == "query"
        assert query.data()["slot"]["prompt"] == "Which fixture?"
        assert plan.compiled.identity.call_sid == "offline-native-simulation"
        assert plan.runtime == {
            "engine": "native_pilot",
            "source": "published",
            "implementation": "NativeFlowAdapter",
            "tool_id": TOOL_ID,
            "assistant_id": str(records.assistant.id),
            "account_id": ACCOUNT,
            "property_id": PROPERTY,
            "flow_version_id": VERSION_ID,
            "version_number": 1,
            "llm_provider": records.assistant.llm_provider,
            "llm_model": records.assistant.llm_model,
            "read_only_global_tools": [],
            "execution_mode": "preview",
            "effect_mode": "simulation",
            "effects_simulated": True,
        }
        assert plan.config.llm_temperature == 0
        assert {entry["key"] for entry in plan.variables_to_collect} == {
            plan.compiled.node("query").data()["slot"]["variableKey"],
            plan.compiled.node("choice").data()["slot"]["variableKey"],
            plan.compiled.node("failure").data()["slot"]["variableKey"],
        }
        assert all(entry["type"] == "string" for entry in plan.variables_to_collect)
        assert len(plan.variables_to_collect) == len({
            entry["key"] for entry in plan.variables_to_collect
        }), "alternative collection nodes must not duplicate a variable in the editor"
        assert plan.variables_to_collect[0]["node_id"] == query.node_id
        arguments["db"].close()
    asyncio.run(scenario())


def test_native_simulator_selects_the_requested_flow_from_multiple_assignments():
    async def scenario():
        module, records, arguments = selection_case(
            extra_published_flow=True, wrong_selection=True,
        )
        plan = await module.prepare_native_simulation(**arguments)
        assert plan.compiled.identity.tool_id == arguments["request"].tool_id
        assert plan.compiled.identity.flow_version_id == str(
            records.rows["FlowVersion"].id,
        )
        assert set(plan.available_flows) == {
            arguments["request"].tool_id, "00000000-0000-0000-0000-000000000110",
        }
        assert plan.global_functions == ()
        from botelier.voice.flows.native_action_preview import NativePreviewResponse
        from botelier.voice.flows.native_text_host import NativeTextHost

        host = NativeTextHost(
            plan.compiled,
            config=plan.config,
            api_keys={"openai_api_key": "offline-test-only"},
            session_factory=records.session,
            available_flows=plan.available_flows,
            preview=plan.preview,
        )
        try:
            host._build_pipeline()
            assert set(host.adapter._flow_catalogue) == set(plan.available_flows)
            task = asyncio.create_task(host._simulate_terminal(
                SimpleNamespace(type="transfer", node_id="transfer"), {},
            ))
            while host.preview.snapshot() is None:
                await asyncio.sleep(0)
            pending = host.preview.snapshot()
            host.preview.submit(
                pending["request_id"],
                NativePreviewResponse(status_code=200, data={"accepted": True}),
            )
            result = await task
            assert result.accepted is True
            assert result.completed is True
            assert host.preview.effects == [{
                "kind": "transfer", "node_id": "transfer", "simulated": True,
            }]
        finally:
            await host.close()
        arguments["db"].close()
    asyncio.run(scenario())


def test_native_simulator_exposes_only_scoped_readonly_mcp_preview_tools():
    async def scenario():
        module, records, arguments = selection_case(with_mcp=True)
        records.rows["MCPConnection"].discovered_tools[0]["parameters"] = {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "object",
                    "description": "Untrusted server text is not model schema.",
                    "properties": {
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "description": "Not copied."},
                        },
                    },
                    "required": ["tags"],
                    "additionalProperties": False,
                },
            },
            "required": ["filter"],
            "additionalProperties": False,
        }
        plan = await module.prepare_native_simulation(**arguments)
        assert [item.name for item in plan.global_functions] == ["lookup"]
        assert plan.runtime["read_only_global_tools"] == ["lookup"]
        from botelier.voice.flows.native_action_preview import NativePreviewResponse
        filter_schema = plan.global_functions[0].properties["filter"]
        assert filter_schema["properties"]["tags"] == {
            "type": "array", "items": {"type": "string"},
        }
        handler_task = asyncio.create_task(plan.global_functions[0].handler(
            {"filter": {"tags": []}}, None,
        ))
        while plan.preview.snapshot() is None:
            await asyncio.sleep(0)
        pending = plan.preview.snapshot()
        response = {"isError": False, "structuredContent": {"found": True}, "content": []}
        plan.preview.submit(
            pending["request_id"],
            NativePreviewResponse(status_code=200, data=response),
        )
        preview = await handler_task
        assert preview == response
        assert "reserve" not in plan.runtime["read_only_global_tools"]
        from botelier.voice.flows.native_text_host import NativeTextHost

        host = NativeTextHost(
            plan.compiled,
            config=plan.config,
            api_keys={"openai_api_key": "offline-test-only"},
            session_factory=records.session,
            global_functions=plan.global_functions,
            preview=plan.preview,
        )
        try:
            host._build_pipeline()
            assert [
                item.name for item in host.adapter.manager._global_functions
            ] == ["lookup"]
        finally:
            await host.close()
        arguments["db"].close()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", [None, "draft", "unsaved"])
def test_native_simulator_requires_explicit_published_source_before_queries(source):
    async def scenario():
        module, _, arguments = selection_case()
        arguments["request"].source = source
        arguments["db"] = object()  # Unsupported sources must not query anything.
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_simulation_published_source_required"
    asyncio.run(scenario())


@pytest.mark.parametrize("source_version", [None, True, "1", 0, -1])
def test_native_simulator_refuses_unversioned_or_coerced_source(source_version):
    async def scenario():
        module, _, arguments = selection_case()
        arguments["request"].source_version = source_version
        arguments["db"] = object()
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_simulation_version_required"
    asyncio.run(scenario())


def test_native_simulator_refuses_a_stale_editor_version_instead_of_switching():
    async def scenario():
        module, _, arguments = selection_case()
        arguments["request"].source_version = 2
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_simulation_version_changed"
        assert error.value.status_code == 409
        arguments["db"].close()
    asyncio.run(scenario())


def test_native_simulator_is_unavailable_in_production_before_metadata_queries():
    async def scenario():
        module, _, arguments = selection_case()
        from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy

        arguments["policy"] = NativeFlowDevPolicy("production", "1")
        arguments["db"] = object()
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_dev_disabled"
        assert error.value.status_code == 403
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "record_options,code",
    [
        ({"wrong_ownership": "property"}, "native_dev_ownership"),
        ({"wrong_ownership": "tool"}, "native_dev_ownership"),
        ({"wrong_ownership": "tool_set"}, "native_dev_ownership"),
        ({"missing_version": True}, "native_dev_published_version"),
        ({"unpublished_version": True}, "native_dev_published_version"),
    ],
)
def test_native_simulator_preserves_voice_ownership_resource_and_source_guards(
    record_options, code,
):
    async def scenario():
        module, _, arguments = selection_case(**record_options)
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == code
        arguments["db"].close()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["assistant", "account", "inactive_tool"])
def test_native_simulator_refuses_mismatched_request_identity_or_inactive_flow(change):
    async def scenario():
        module, _, arguments = selection_case()
        if change == "assistant":
            arguments["request"].assistant_id = "another-assistant"
        elif change == "account":
            arguments["account_id"] = "another-account"
        else:
            arguments["tool"].is_active = "false"
        with pytest.raises(module.NativeSimulationError):
            await module.prepare_native_simulation(**arguments)
        arguments["db"].close()
    asyncio.run(scenario())


def test_native_simulator_does_not_substitute_an_unavailable_provider_or_model():
    async def scenario():
        module, records, arguments = selection_case()
        records.assistant.llm_provider = "anthropic"
        records.assistant.llm_model = "configured-other-model"
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_simulation_provider_unsupported"
        assert records.assistant.llm_model == "configured-other-model"
        arguments["db"].close()
    asyncio.run(scenario())


def test_native_simulator_uses_the_configured_google_model_and_sdk_context(monkeypatch):
    async def scenario():
        module, records, arguments = selection_case()
        records.assistant.llm_provider = "google_gemini"
        records.assistant.llm_model = "gemini-2.5-flash"
        records.assistant.temperature = 0.35
        records.assistant.max_tokens = 333
        records.assistant.llm_config = {"top_p": 0.8}
        try:
            google_sdk_available = importlib.util.find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            google_sdk_available = False
        if not google_sdk_available:
            with pytest.raises(module.NativeSimulationError) as error:
                await module.prepare_native_simulation(**arguments)
            assert error.value.code == "native_simulation_provider_unsupported"
            arguments["db"].close()
            return

        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from pipecat.adapters.schemas.tools_schema import ToolsSchema
        from pipecat.adapters.services.gemini_adapter import GeminiLLMAdapter
        from pipecat.processors.aggregators.llm_context import LLMContext
        from botelier.voice.engine import VoiceEngineFactory

        plan = await module.prepare_native_simulation(**arguments)
        assert plan.config.llm_provider == "google_gemini"
        assert plan.config.llm_model == "gemini-2.5-flash"
        monkeypatch.setenv("GOOGLE_API_KEY", "offline-google-key")
        monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-selected")
        assert module.native_model_api_keys(plan.config) == {
            "google_api_key": "offline-google-key",
        }

        service = VoiceEngineFactory.create_llm_service(
            plan.config, {"google_api_key": "offline-google-key"},
        )
        assert service._settings.model == "gemini-2.5-flash"
        assert service._settings.temperature == 0.35
        assert service._settings.max_tokens == 333
        assert service._settings.top_p == 0.8

        context = LLMContext(
            messages=[{"role": "user", "content": "Check availability."}],
            tools=ToolsSchema(standard_tools=[
                FunctionSchema("lookup_fixture", "Lookup only.", {}, []),
            ]),
        )
        invocation = GeminiLLMAdapter().get_llm_invocation_params(context)
        assert invocation["tools"][0]["functionDeclarations"][0]["name"] == (
            "lookup_fixture"
        )
        arguments["db"].close()
    asyncio.run(scenario())

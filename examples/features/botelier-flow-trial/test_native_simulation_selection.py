"""Native Test Lab source admission; no server, providers or customer storage."""

import asyncio
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
        assert plan.compiled.query.node_id == "query"
        assert plan.compiled.query.prompt == "Which fixture?"
        assert plan.compiled.identity.call_sid == "offline-native-simulation"
        assert plan.runtime == {
            "engine": "native_pilot",
            "source": "published",
            "tool_id": TOOL_ID,
            "assistant_id": str(records.assistant.id),
            "account_id": ACCOUNT,
            "property_id": PROPERTY,
            "flow_version_id": VERSION_ID,
            "version_number": 1,
            "llm_provider": records.assistant.llm_provider,
            "llm_model": records.assistant.llm_model,
        }
        assert plan.config.llm_temperature == 0
        assert {entry["key"] for entry in plan.variables_to_collect} == {
            plan.compiled.query.variable,
            plan.compiled.choice.variable,
            plan.compiled.failure.variable,
        }
        assert all(entry["type"] == "string" for entry in plan.variables_to_collect)
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
        ({"wrong_selection": True}, "native_dev_selection"),
        ({"extra_tool": True}, "native_dev_resources"),
        ({"with_mcp": True}, "native_dev_resources"),
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


def test_native_simulator_does_not_substitute_an_unverified_provider_or_model():
    async def scenario():
        module, records, arguments = selection_case()
        records.assistant.llm_provider = "google_gemini"
        records.assistant.llm_model = "configured-other-model"
        with pytest.raises(module.NativeSimulationError) as error:
            await module.prepare_native_simulation(**arguments)
        assert error.value.code == "native_simulation_provider_unsupported"
        assert records.assistant.llm_model == "configured-other-model"
        arguments["db"].close()
    asyncio.run(scenario())

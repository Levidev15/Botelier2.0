"""Full-catalog admission at the real development host/source boundary."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from application_support import load_function_mapper
from native_graph_io import full_catalog_config


def selection_case():
    load_function_mapper()
    from native_dev_voice_io import NativeDevRecords
    from node_contract_io import PROPERTY
    from botelier.voice.flows.native_dev_host import prepare_native_dev_selection

    records = NativeDevRecords()
    records.rows["FlowVersion"].flow_config = full_catalog_config()
    arguments = dict(
        assistant=records.assistant,
        tools=records.rows["Tool"],
        tool_set=records.rows["ToolSet"],
        flow_version=records.rows["FlowVersion"],
        call_sid="offline-full-catalog-host",
        property_id=PROPERTY,
        property_owned=True,
    )
    return prepare_native_dev_selection, records, arguments


def test_voice_admission_compiles_all_fifteen_nodes_with_exact_private_config():
    prepare, records, arguments = selection_case()
    from botelier.voice.flows.native_graph import CompiledFlow

    config = full_catalog_config()
    records.rows["FlowVersion"].flow_config = config
    selection = prepare(**arguments)
    assert isinstance(selection.compiled, CompiledFlow)
    assert len({node.type for node in selection.compiled.nodes}) == 15
    assert selection.compiled.config()["globalPrompt"] == config["globalPrompt"]
    assert selection.compiled.identity.flow_version_id == records.rows["FlowVersion"].id
    config["globalPrompt"] = "Changed after admission"
    assert selection.compiled.config()["globalPrompt"] != config["globalPrompt"]


def test_voice_admission_allows_additional_owned_node_bound_tools():
    prepare, records, arguments = selection_case()
    from botelier.models.tool import ToolType

    arguments["tools"].append(SimpleNamespace(
        id="offline-send-link", tool_type=ToolType.SEND_SMS,
        account_id=None, tool_set_id=records.assistant.tool_set_id, is_active="true",
    ))
    selection = prepare(**arguments)
    assert selection.tool.id == records.assistant.call_settings["native_flow_tool_id"]


def test_voice_admission_resolves_the_named_flow_not_the_first_flow_in_a_tool_set():
    prepare, records, arguments = selection_case()
    tool = SimpleNamespace(**deepcopy(vars(records.rows["Tool"][0])))
    tool.id = "offline-second-flow"
    tool.published_version_id = "offline-second-version"
    arguments["tools"].append(tool)
    records.assistant.call_settings["native_flow_tool_id"] = tool.id
    version = SimpleNamespace(**deepcopy(vars(arguments["flow_version"])))
    version.id, version.tool_id = tool.published_version_id, tool.id
    arguments["flow_version"] = version
    selection = prepare(**arguments)
    assert selection.tool is tool
    assert selection.compiled.identity.tool_id == tool.id
    assert selection.compiled.identity.flow_version_id == version.id


@pytest.mark.parametrize("change", ["inactive", "duplicate"])
def test_voice_admission_refuses_inactive_or_ambiguous_selected_flow(change):
    prepare, records, arguments = selection_case()
    from botelier.voice.flows.native_dev_host import NativeDevAdmissionError

    if change == "inactive":
        records.rows["Tool"][0].is_active = "false"
    else:
        arguments["tools"].append(deepcopy(records.rows["Tool"][0]))
    with pytest.raises(NativeDevAdmissionError):
        prepare(**arguments)


def test_test_lab_can_select_an_owned_published_flow_without_changing_voice_routing():
    async def scenario():
        from test_native_simulation_selection import selection_case as simulation_case

        module, records, arguments = simulation_case(extra_tool=True)
        config = full_catalog_config()
        records.rows["FlowVersion"].flow_config = config
        original_settings = {"native_flow_tool_id": "offline-other-voice-flow"}
        records.assistant.call_settings = deepcopy(original_settings)
        try:
            plan = await module.prepare_native_simulation(**arguments)
            assert len({node.type for node in plan.compiled.nodes}) == 15
            assert {item["key"] for item in plan.variables_to_collect} == {
                slot.variable for slot in plan.compiled.caller_slots
            }
            assert records.assistant.call_settings == original_settings
            assert plan.runtime["implementation"] == "NativeFlowAdapter"
        finally:
            arguments["db"].close()

    asyncio.run(scenario())

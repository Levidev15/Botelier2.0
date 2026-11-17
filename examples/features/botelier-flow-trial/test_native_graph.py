"""Guarded contract tests for the reusable immutable native graph compiler."""

from dataclasses import FrozenInstanceError
import importlib
import json
import re
import sys

import pytest


IDENTITY_FIELDS = {
    "account_id": "00000000-0000-0000-0000-000000000101",
    "property_id": "00000000-0000-0000-0000-000000000102",
    "tool_id": "offline-flow",
    "flow_version_id": "offline-version",
    "call_sid": "CAofflinefixture",
}


def graph_api():
    return importlib.import_module("botelier.voice.flows.native_graph")


def identity():
    pilot = importlib.import_module("botelier.voice.flows.pilot_contract")
    return pilot.PilotIdentity(**IDENTITY_FIELDS)


def node(node_id, node_type, data):
    return {"id": node_id, "type": node_type, "data": data}


def edge(source, target, handle=None):
    result = {"id": f"{source}-{handle or 'default'}-{target}",
              "source": source, "target": target}
    if handle is not None:
        result["sourceHandle"] = handle
    return result


def sample_node(node_type):
    common = {"name": node_type}
    samples = {
        "initial": {"systemPrompt": "", "greeting": "Welcome", "waitForResponse": True},
        "message": {"message": "Hello {{name}}", "waitForResponse": True},
        "collect_slot": {"slot": {"variableKey": "name", "prompt": "Your name?",
                                    "type": "text", "maxRetries": 0}},
        "collect_form": {"slots": [{"id": "slot_name", "order": 0,
                                     "variableKey": "name", "prompt": "Your name?",
                                     "type": "text", "maxRetries": 0}]},
        "api_request": {"api": {"method": "POST", "url": "https://example.invalid/path",
                                "bodyTemplate": "{\"name\":\"{{name}}\"}",
                                "timeout": 8, "retryCount": 0}},
        "api_response": {"responsePresentation": {"arrayVariable": "items",
                                                    "itemTemplate": "{{item}}"}},
        "condition": {"condition": {"variable": "name", "operator": "is_not_empty",
                                     "value": ""}},
        "router": {"router": {"variable": "choice", "options": [
            {"id": "opt_a", "value": "a", "label": "A"}]}},
        "confirmation": {"confirmation": {"summaryTemplate": "Name: {{name}}",
                                           "confirmPrompt": "Correct?",
                                           "variablesToConfirm": ["name"],
                                           "allowEdit": False}},
        "set_variable": {"setVariable": {"variableKey": "name", "valueType": "static",
                                          "value": ""}},
        "save_record": {"saveRecord": {"recordTypeId": "record_type_1",
                                        "mapping": {"name": "{{name}}"}}},
        "transfer": {"transfer": {"phoneNumber": "+15555550100",
                                   "warmTransfer": False}},
        "capability": {"api": {"apiSource": "capability", "method": "GET",
                               "capability": "availability"}},
        "option_picker": {"optionPicker": {"sourceVariable": "items",
                                            "labelPath": "name",
                                            "prompt": "Which one?",
                                            "maxRetries": 0,
                                            "writes": [{"variableKey": "name",
                                                        "path": "name"}]}},
        "end": {"closingMessage": "Goodbye"},
    }
    return {**common, **samples[node_type]}


def test_normal_compiler_import_is_pure_without_synthetic_package_modules():
    compiler = graph_api()
    assert compiler.__file__.endswith("/botelier/voice/flows/native_graph.py")
    assert "botelier.voice.call_handler" not in sys.modules
    assert "botelier.services.call_logger" not in sys.modules
    assert "botelier.services.mcp_client" not in sys.modules


def config_for(node_type):
    selected = node("target", node_type, sample_node(node_type))
    nodes = [
        node("start", "initial", {"name": "Start", "systemPrompt": "",
                                  "greeting": "Hello", "waitForResponse": True}),
        selected,
        node("finish", "end", {"name": "End", "closingMessage": ""}),
    ]
    edges = [edge("start", "target")]
    if node_type == "condition":
        nodes.append(node("else", "end", {"name": "Else", "closingMessage": ""}))
        edges.extend([edge("target", "finish", "true"), edge("target", "else", "false")])
    elif node_type == "api_response":
        nodes.append(node("else", "end", {"name": "Else", "closingMessage": ""}))
        edges.extend([
            edge("target", "finish", "has_results"),
            edge("target", "else", "no_results"),
        ])
    elif node_type == "router":
        nodes.append(node("else", "end", {"name": "Else", "closingMessage": ""}))
        edges.extend([edge("target", "finish", "opt_a"), edge("target", "else", "fallback")])
    elif node_type == "confirmation":
        edges.append(edge("target", "finish", "confirmed"))
    elif node_type == "initial":
        return {
            "initial_node": "target",
            "nodes": [selected, nodes[-1]],
            "edges": [edge("target", "finish")],
            "variables": [],
        }
    elif node_type in {"end", "transfer"}:
        return {
            "initial_node": "start",
            "nodes": [nodes[0], selected],
            "edges": [edge("start", "target")],
            "variables": [],
        }
    else:
        edges.append(edge("target", "finish"))
    declarations = {
        "name": {"key": "name", "type": "text", "description": "", "required": True},
        "choice": {"key": "choice", "type": "choice", "description": "",
                   "required": True, "choices": ["a"]},
        "items": {"key": "items", "type": "text", "description": "", "required": False},
    }
    return {
        "initial_node": "start",
        "nodes": nodes,
        "edges": edges,
        "variables": list(declarations.values()),
        "globalPrompt": "",
    }


@pytest.mark.parametrize("node_type", [
    "initial", "message", "collect_slot", "collect_form", "api_request",
    "api_response", "condition", "router", "confirmation", "set_variable",
    "save_record", "transfer", "capability", "option_picker", "end",
])
def test_each_current_editor_node_type_is_admitted(node_type):
    compiled = graph_api().compile_flow(config_for(node_type), identity())
    assert isinstance(compiled.nodes, tuple)
    assert compiled.node("target").type == node_type


@pytest.mark.parametrize("slot_type", [
    "text", "date", "number", "phone", "email", "time", "choice",
])
def test_each_supported_caller_slot_type_is_admitted(slot_type):
    config = config_for("collect_slot")
    slot = config["nodes"][1]["data"]["slot"]
    slot.update(variableKey="answer", type=slot_type)
    declaration = config["variables"][0]
    declaration.update(key="answer", type=slot_type)
    if slot_type == "choice":
        declaration["choices"] = ["first", "second"]
    compiled = graph_api().compile_flow(config, identity())
    assert compiled.caller_slots[0].type == slot_type


def test_integrations_and_safe_expressions_are_admitted_without_resolution_or_evaluation():
    api_config = config_for("api_request")
    api = api_config["nodes"][1]["data"]["api"]
    api.update(apiSource="integration", integrationId=IDENTITY_FIELDS["account_id"],
               endpointId="search-v1", path="/search?name={{name}}",
               responseMapping={"name": "$.results[0].name"},
               responseProjection={"fields": [{"variable": "name", "cleanup": ["trim"]}]})
    compiled_api = graph_api().compile_flow(api_config, identity())
    assert compiled_api.node("target").data()["api"]["responseProjection"]["fields"][0]["cleanup"] == ["trim"]

    expression_config = config_for("set_variable")
    expression_config["nodes"][1]["data"]["setVariable"].update(
        valueType="expression", value="'literal' + ' text'",
    )
    compiled_expression = graph_api().compile_flow(expression_config, identity())
    assert compiled_expression.node("target").data()["setVariable"]["value"] == "'literal' + ' text'"


def test_json_path_root_is_explicit_and_option_picker_empty_path_means_whole_item():
    config = config_for("api_request")
    config["nodes"][1]["data"]["api"]["responseMapping"] = {"name": ""}
    with pytest.raises(graph_api().NativeGraphError, match="api_mapping"):
        graph_api().compile_flow(config, identity())

    config["nodes"][1]["data"]["api"]["responseMapping"] = {"name": "$"}
    assert graph_api().compile_flow(config, identity()).node("target")

    picker = config_for("option_picker")
    picker["nodes"][1]["data"]["optionPicker"]["writes"][0]["path"] = ""
    assert graph_api().compile_flow(picker, identity()).node("target")


def test_api_item_templates_use_provider_item_fields_not_flow_variable_names():
    config = config_for("api_response")
    config["nodes"][1]["data"]["responsePresentation"]["itemTemplate"] = (
        "{{room_name}} costs {{price}} at index {{index}}"
    )
    compiled = graph_api().compile_flow(config, identity())
    assert "{{price}}" in compiled.node("target").data()["responsePresentation"]["itemTemplate"]


def test_representative_combined_flow_preserves_configured_native_controls():
    cfg = {
        "initial_node": "start",
        "globalPrompt": "Private flow guidance",
        "variables": [
            {"key": "name", "type": "text", "description": "", "required": True},
            {"key": "choice", "type": "choice", "description": "", "required": True,
             "choices": ["a"]},
            {"key": "items", "type": "text", "description": "", "required": False},
        ],
        "nodes": [
            node("start", "initial", {"name": "Start", "systemPrompt": "",
                                      "greeting": "Welcome", "waitForResponse": True}),
            node("form", "collect_form", {"name": "Details", "introMessage": "",
                                          "slots": [{"id": "form_name", "order": 0,
                                                     "variableKey": "name", "prompt": "Name?",
                                                     "type": "text", "maxRetries": 0}]}),
            node("request", "api_request", {"name": "Lookup", "api": {
                "apiSource": "custom", "method": "GET", "url": "https://example.invalid/items",
                "responseMapping": {"items": "$.items"}, "timeout": 8, "retryCount": 0,
                "responseProjection": {"fields": [{"variable": "items"}]},
            }}),
            node("condition", "condition", {"name": "Has name", "condition": {
                "variable": "name", "operator": "is_not_empty", "value": "",
            }}),
            node("router", "router", {"name": "Route", "router": {
                "variable": "choice", "options": [{"id": "opt_a", "value": "a", "label": "A"}],
            }}),
            node("response", "api_response", {"name": "Present", "responsePresentation": {
                "arrayVariable": "items", "itemTemplate": "{{item}}", "noResultsText": "None",
            }}),
            node("picker", "option_picker", {"name": "Select", "optionPicker": {
                "sourceVariable": "items", "labelPath": "name", "prompt": "Which?",
                "writes": [{"variableKey": "name", "path": "name"}],
            }}),
            node("confirm", "confirmation", {"name": "Confirm", "confirmation": {
                "summaryTemplate": "Name {{name}}", "confirmPrompt": "Correct?",
                "editPrompt": "What should change?", "variablesToConfirm": ["name"],
                "allowEdit": True,
            }}),
            node("set", "set_variable", {"name": "Set", "setVariable": {
                "variableKey": "name", "valueType": "template", "value": "{{name}}",
            }}),
            node("record", "save_record", {"name": "Save", "saveRecord": {
                "recordTypeId": "record-type-1", "mapping": {"guest_name": "{{name}}"},
            }}),
            node("failure", "message", {"name": "Failure", "message": "No results",
                                         "waitForResponse": True}),
            node("end", "end", {"name": "End", "closingMessage": "Goodbye"}),
        ],
        "edges": [
            edge("start", "form"), edge("form", "request"),
            edge("request", "condition", "success"), edge("request", "failure", "error"),
            edge("condition", "router", "true"), edge("condition", "failure", "false"),
            edge("router", "response", "opt_a"), edge("router", "failure", "fallback"),
            edge("response", "picker", "has_results"),
            edge("response", "failure", "no_results"),
            edge("picker", "confirm", "selected"), edge("picker", "failure", "fallback"),
            edge("confirm", "set", "confirmed"), edge("confirm", "form", "edit"),
            edge("set", "record"), edge("record", "end"), edge("failure", "end"),
        ],
    }
    compiled = graph_api().compile_flow(cfg, identity())
    assert compiled.next_node("confirm", "confirmed").node_id == "set"
    assert compiled.next_node("request", "success").node_id == "condition"
    assert compiled.config()["nodes"][4]["data"]["router"]["options"][0]["label"] == "A"


def test_graph_config_is_independent_frozen_and_ui_metadata_is_behavior_neutral():
    config = config_for("message")
    config["nodes"][1].update(position={"x": 99, "y": 12}, selected=True,
                              style={"stroke": "pink"})
    compiled = graph_api().compile_flow(config, identity())
    original = compiled.config()
    config["nodes"][1]["data"]["message"] = "Changed"
    original["nodes"][1]["data"]["message"] = "Changed by consumer"
    assert compiled.node("target").data()["message"] == "Hello {{name}}"
    assert compiled.config()["nodes"][1]["data"]["message"] == "Hello {{name}}"
    node_data = compiled.node("target").data()
    node_data["message"] = "mutable copy"
    assert compiled.node("target").data()["message"] == "Hello {{name}}"
    with pytest.raises(FrozenInstanceError):
        compiled.node("target").node_id = "replaced"


def test_arbitrary_condition_router_fallback_and_legacy_default_edges_are_resolved():
    config = config_for("condition")
    config["nodes"][1]["data"]["condition"]["trueTarget"] = "finish"
    config["nodes"][1]["data"]["condition"]["falseTarget"] = "else"
    compiled = graph_api().compile_flow(config, identity())
    assert compiled.next_node("target", "true").node_id == "finish"
    assert compiled.next_node("target", "false").node_id == "else"
    assert compiled.next_node("target") is None

    router = config_for("router")
    compiled_router = graph_api().compile_flow(router, identity())
    assert compiled_router.next_node("target", "opt_a").node_id == "finish"
    assert compiled_router.next_node("target", "fallback").node_id == "else"
    assert compiled_router.next_node("target") is None

    legacy = config_for("confirmation")
    legacy["edges"][1].pop("sourceHandle")
    legacy["edges"][1]["id"] = "legacy-confirmed-default"
    compiled_legacy = graph_api().compile_flow(legacy, identity())
    assert compiled_legacy.next_node("target", "confirmed").node_id == "finish"

    legacy_success = config_for("api_request")
    compiled_success = graph_api().compile_flow(legacy_success, identity())
    assert compiled_success.next_node("target", "success").node_id == "finish"
    assert compiled_success.next_node("target", "unknown") is None
    assert compiled_success.next_node("target", "error") is None
    assert compiled_success.next_node("target", "not_found") is None
    assert compiled_success.next_node("target", {"success": True}) is None
    assert compiled_legacy.next_node("target", "unrecognized") is None


def test_bounded_wait_cycle_is_allowed_but_automatic_cycle_is_rejected():
    config = config_for("message")
    config["nodes"][-1] = node(
        "finish", "message", {"name": "Wait", "message": "Again?", "waitForResponse": True},
    )
    config["edges"].append(edge("finish", "target"))
    compiled = graph_api().compile_flow(config, identity())
    assert compiled.next_node("finish").node_id == "target"

    automatic = config_for("set_variable")
    automatic["nodes"][-1] = node(
        "finish", "set_variable", {"name": "Set", "setVariable": {
            "variableKey": "name", "valueType": "static", "value": "x",
        }},
    )
    automatic["edges"][-1] = edge("target", "finish")
    automatic["edges"].append(edge("finish", "target"))
    with pytest.raises(graph_api().NativeGraphError, match="cycle"):
        graph_api().compile_flow(automatic, identity())


@pytest.mark.parametrize("invalid", [
    "too_many_nodes", "bad_id", "unknown_target", "duplicate_handle",
    "unknown_field", "undeclared_template", "unsafe_expression", "terminal_edge",
    "malformed_type", "malformed_edge", "malformed_router_variable",
    "wrong_initial", "unreachable_node",
])
def test_invalid_graphs_fail_with_stable_non_leaking_diagnostics(invalid):
    config = config_for("message")
    secret = "sensitive-prompt-https://secret.invalid/api"
    if invalid == "too_many_nodes":
        config["nodes"] = [node(f"n{i}", "message", {"message": "x"}) for i in range(300)]
    elif invalid == "bad_id":
        config["nodes"][1]["id"] = "../" + secret
    elif invalid == "unknown_target":
        config["edges"][0]["target"] = secret
    elif invalid == "duplicate_handle":
        config["edges"].append(edge("start", "finish"))
    elif invalid == "unknown_field":
        config["nodes"][1]["data"]["untrusted_payload"] = secret
    elif invalid == "undeclared_template":
        config["nodes"][1]["data"]["message"] = "{{private_value}}"
    elif invalid == "unsafe_expression":
        config["nodes"][1] = node("target", "set_variable", {
            "name": "Set", "setVariable": {
                "variableKey": "name", "valueType": "expression",
                "value": "__import__('os').system('echo secret')",
            },
        })
    elif invalid == "terminal_edge":
        config["edges"].append(edge("finish", "target"))
    elif invalid == "malformed_type":
        config["nodes"][1]["type"] = []
    elif invalid == "malformed_edge":
        config["edges"][0]["source"] = []
    elif invalid == "malformed_router_variable":
        config["nodes"][1] = node("target", "router", {
            "name": "Router", "router": {"variable": [], "options": []},
        })
    elif invalid == "wrong_initial":
        config["initial_node"] = "target"
    elif invalid == "unreachable_node":
        config["nodes"].append(node("hidden", "message", {
            "name": "Hidden", "message": "Not reachable",
        }))

    with pytest.raises(graph_api().NativeGraphError) as caught:
        graph_api().compile_flow(config, identity())
    diagnostic = str(caught.value)
    assert re.fullmatch(r"[a-z_]+(?::[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?)?", diagnostic)
    assert secret not in diagnostic
    assert "sensitive-prompt" not in diagnostic


def test_template_copy_and_false_zero_configuration_values_are_preserved():
    config = config_for("collect_slot")
    config["nodes"][1]["data"]["slot"].update(maxRetries=0, useBuiltInValidator=False)
    compiled = graph_api().compile_flow(config, identity())
    stored = compiled.config()["nodes"][1]["data"]["slot"]
    assert stored["maxRetries"] == 0
    assert stored["useBuiltInValidator"] is False
    assert compiled.caller_slots[0].variable == "name"
    assert compiled.native_names
    assert compiled.max_nodes >= len(compiled.nodes)
    assert compiled.max_total_io_bytes >= 0

"""Reject unsupported saved graphs before a native worker or action exists."""

from dataclasses import FrozenInstanceError
from copy import deepcopy
import importlib
import importlib.util

import pytest

from pilot_io import IDENTITY_FIELDS, pilot_config


def contract():
    module = "botelier.voice.flows.pilot_contract"
    assert importlib.util.find_spec(module) is not None, (
        "The approved saved-graph admission compiler is not implemented"
    )
    return importlib.import_module(module)


def compile_graph(config=None):
    api = contract()
    return api.compile_pilot(
        pilot_config() if config is None else config, api.PilotIdentity(**IDENTITY_FIELDS),
    )


def test_compiled_graph_retains_saved_ids_and_reserves_future_collection_names():
    compiled = compile_graph()
    assert compiled.query.node_id == "query"
    assert compiled.choice.node_id == "choice"
    assert compiled.failure.node_id == "failure"
    assert compiled.api_node_id == "lookup"
    assert compiled.response_node_id == "response"
    assert compiled.native_names == {
        "collect_query", "collect_choice", "collect_failure",
    }
    assert compiled.identity.account_id == "00000000-0000-0000-0000-000000000101"
    assert compiled.identity.property_id == "00000000-0000-0000-0000-000000000102"


def test_active_definition_and_identity_cannot_be_mutated_by_the_source_or_consumers():
    config = pilot_config()
    compiled = compile_graph(config)
    config["nodes"][1]["data"]["slot"]["prompt"] = "Changed after admission"
    config["nodes"][2]["data"]["api"]["method"] = "POST"
    config["nodes"][2]["data"]["api"]["integrationId"] = "different-connection"
    assert compiled.query.prompt == "Which fixture?"
    assert compiled.api_config()["method"] == "GET"
    assert compiled.api_config()["integrationId"] == "00000000-0000-0000-0000-000000000103"
    consumer_copy = compiled.api_config()
    consumer_copy["method"] = "POST"
    assert compiled.api_config()["method"] == "GET"
    with pytest.raises(FrozenInstanceError):
        compiled.identity.property_id = "different-property"
    with pytest.raises(FrozenInstanceError):
        compiled.query.prompt = "Changed by consumer"


@pytest.mark.parametrize("node_id", ["lookup", "response"])
def test_rejects_private_automatic_node_instructions_instead_of_ignoring_them(node_id):
    config = pilot_config()
    next(node for node in config["nodes"] if node["id"] == node_id)["data"][
        "instructions"
    ] = "Private instructions that require a model decision"
    with pytest.raises(contract().PilotAdmissionError, match="automatic_instructions"):
        compile_graph(config)


@pytest.mark.parametrize("mutate,reason", [
    (lambda c: c["nodes"].append(c["nodes"][0].copy()), "node_ids"),
    (lambda c: c["nodes"][0].pop("id"), "node_ids"),
    (lambda c: c["edges"][0].update(target="absent"), "edges"),
    (lambda c: c["edges"].append({"source": "choice", "target": "query"}), "topology"),
    (lambda c: c["edges"].append({
        "source": "lookup", "target": "choice", "sourceHandle": "success",
    }), "edges"),
    (lambda c: c["edges"].pop(), "topology"),
    (lambda c: c["nodes"].append({
        "id": "unused", "type": "message", "data": {"message": "Omitted"},
    }), "node_types"),
    (lambda c: c["nodes"][2].update(type="save_record"), "node_types"),
    (lambda c: c.update(initial_node="query"), "topology"),
    (lambda c: c["nodes"][0]["data"].update(greeting="Hello again"), "initial"),
    (lambda c: c["nodes"][0]["data"].update(waitForResponse=True), "initial"),
    (lambda c: c["nodes"][1]["data"]["slot"].update(prompt=" "), "slot"),
    (lambda c: c["nodes"][1]["data"]["slot"].update(required=False), "slot"),
    (lambda c: c["nodes"][1]["data"]["slot"].update(validation={"minLength": 3}), "slot"),
    (lambda c: c["nodes"][1]["data"]["slot"].update(unknownControl=True), "slot"),
    (lambda c: c["variables"][0].update(type="number"), "variables"),
    (lambda c: c["variables"].pop(0), "variables"),
    (lambda c: c["nodes"][1].update(id="query / unsafe"), "node_ids"),
    (lambda c: c["nodes"][2]["data"]["api"].update(apiSource="custom"), "connected_get"),
    (lambda c: c["nodes"][2]["data"]["api"].update(method="POST"), "connected_get"),
    (lambda c: c["nodes"][2]["data"]["api"].update(integrationId=""), "connected_get"),
    (lambda c: c["nodes"][2]["data"]["api"].update(headers={"X-Key": "untrusted"}), "api_fields"),
    (lambda c: c["nodes"][2]["data"]["api"].update(bodyTemplate="{}"), "api_fields"),
    (lambda c: c["nodes"][2]["data"]["api"].update(queryParamOverrides={"hotel": "other"}), "api_fields"),
    (lambda c: c["nodes"][2]["data"]["api"].update(path="//other.invalid"), "request_template"),
    (lambda c: c["nodes"][2]["data"]["api"].update(path="https://other.invalid"), "request_template"),
    (lambda c: c["nodes"][2]["data"]["api"].update(path="/{{secrets.key}}"), "request_template"),
    (lambda c: c["nodes"][2]["data"]["api"].update(path="/{{unknown}}"), "request_template"),
    (lambda c: c["nodes"][2]["data"]["api"].update(path="/{query}"), "request_template"),
    (lambda c: c["nodes"][2]["data"]["api"].update(retryCount=20), "request_limits"),
    (lambda c: c["nodes"][2]["data"]["api"].update(timeout=True), "request_limits"),
    (lambda c: c["nodes"][2]["data"]["api"].update(onComplete="A second result"), "speech"),
    (lambda c: c["nodes"][2]["data"]["api"].update(responseInstructions="Speak {{price}}"), "speech"),
    (lambda c: c["nodes"][2]["data"]["api"]["responseMapping"].update(query="$.rooms"), "mapping"),
    (lambda c: c["nodes"][2]["data"]["api"]["responseMapping"].update(_state="$.rooms"), "mapping"),
    (lambda c: c["nodes"][2]["data"]["api"]["responseMapping"].pop("rooms"), "mapping"),
    (lambda c: c["nodes"][-1]["data"]["responsePresentation"].update(outroText="A different question?"), "speech"),
    (lambda c: c["nodes"][-1]["data"]["responsePresentation"].update(itemTemplate="{{secrets.key}}"), "presentation"),
    (lambda c: c["nodes"][2].update(type=[]), "node_types"),
    (lambda c: c["edges"][0].update(source={}), "edges"),
    (lambda c: c["edges"][0].update(target=[]), "edges"),
    (lambda c: c["nodes"][-1]["data"]["responsePresentation"].update(arrayVariable=[]), "mapping"),
])
def test_unsupported_or_ambiguous_definitions_fail_admission(mutate, reason):
    config = pilot_config()
    mutate(config)
    with pytest.raises(contract().PilotAdmissionError, match=reason):
        compile_graph(config)


@pytest.mark.parametrize("outro", ["", "  WHICH   option? "])
def test_an_empty_or_equivalent_outro_does_not_replace_the_next_prompt(outro):
    config = pilot_config()
    config["nodes"][-1]["data"]["responsePresentation"]["outroText"] = outro
    compiled = compile_graph(config)
    assert compiled.choice.prompt == "Which option?"


def test_explicit_response_variable_paths_override_the_mapping_without_mutating_inputs():
    config = pilot_config()
    config["nodes"][2]["data"]["api"]["responseVariables"] = [
        {"variableKey": "price", "jsonPath": "$.rooms[0].price"},
    ]
    compiled = compile_graph(config)
    assert compiled.response_mappings == (
        ("price", "$.rooms[0].price"), ("rooms", "$.rooms"),
    )


def test_collection_private_guidance_is_retained_separately_from_public_prompt():
    compiled = compile_graph()
    assert compiled.query.instructions == "Private node guidance: use only the fixture results."
    assert compiled.query.prompt == "Which fixture?"


def editor_config():
    """An equivalent saved definition with real editor endpoint metadata."""
    config = pilot_config()
    config["globalPrompt"] = ""
    config["nodes"][0]["data"]["systemPrompt"] = ""
    config["variables"].extend([
        {"key": "rooms", "type": "text", "description": "Mapped room options"},
        {"key": "price", "type": "number", "description": "Mapped endpoint price"},
    ])
    for node in config["nodes"]:
        if node["type"] == "collect_slot":
            node["data"]["slot"]["retryPrompt"] = ""
    api = config["nodes"][2]["data"]["api"]
    api["url"] = api.pop("path")
    api.update(
        integrationSlug="offline-fixture",
        endpointId="search_rooms",
        endpointName="Search rooms",
        autoMappingSource={"rooms": "$.rooms", "price": "$.rooms[0].price"},
        headers={"Content-Type": "application/json"},
        bodyTemplate="",
        queryParamOverrides={},
        onNotFound="",
        onAuthError="",
        retryDelay=1000,
    )
    return config


def test_saved_editor_endpoint_compiles_without_editing_its_definition():
    config = editor_config()
    before = deepcopy(config)
    compiled = compile_graph(config)
    assert compiled.api_config()["path"] == "/search?query={{query}}"
    assert compiled.api_config()["endpointId"] == "search_rooms"
    assert compiled.api_config()["method"] == "GET"
    assert compiled.api_config()["integrationId"] == "00000000-0000-0000-0000-000000000103"
    assert compiled.response_mappings == (("rooms", "$.rooms"), ("price", "$.rooms[0].price"))
    assert compiled.query.instructions == "Private node guidance: use only the fixture results."
    assert config == before


def test_equivalent_url_and_path_have_one_immutable_request_target():
    config = editor_config()
    config["nodes"][2]["data"]["api"]["path"] = "/search?query={{query}}"
    compiled = compile_graph(config)
    assert compiled.api_config()["path"] == "/search?query={{query}}"
    assert "url" not in compiled.api_config()
    config["nodes"][2]["data"]["api"]["url"] = "/different"
    assert compiled.api_config()["path"] == "/search?query={{query}}"


def test_disagreeing_editor_and_runtime_paths_are_rejected_instead_of_shadowed():
    config = editor_config()
    config["nodes"][2]["data"]["api"]["path"] = "/different"
    with pytest.raises(contract().PilotAdmissionError, match="request_path_conflict"):
        compile_graph(config)


@pytest.mark.parametrize("url", [
    "https://other.invalid/search", "//other.invalid/search",
    "/{{secrets.key}}", "/{{unknown}}", "/search\r\nAuthorization: value",
])
def test_editor_url_alias_cannot_bypass_request_target_validation(url):
    config = editor_config()
    config["nodes"][2]["data"]["api"]["url"] = url
    with pytest.raises(contract().PilotAdmissionError, match="request_template"):
        compile_graph(config)


@pytest.mark.parametrize("endpoint_id", ["", None, [], {}, "{{query}}", "x" * 129])
def test_editor_endpoint_metadata_must_be_a_bounded_static_identity(endpoint_id):
    config = editor_config()
    config["nodes"][2]["data"]["api"]["endpointId"] = endpoint_id
    with pytest.raises(contract().PilotAdmissionError, match="endpoint_identity"):
        compile_graph(config)


def test_mapping_provenance_does_not_replace_the_operators_selected_mapping():
    config = editor_config()
    api = config["nodes"][2]["data"]["api"]
    api["autoMappingSource"] = {"rooms": "$.originalRooms"}
    api["responseMapping"] = {"rooms": "$.rooms", "price": "$.rooms[0].price"}
    assert compile_graph(config).response_mappings == (
        ("rooms", "$.rooms"), ("price", "$.rooms[0].price"),
    )


@pytest.mark.parametrize("changes,reason", [
    ({"headers": {"Authorization": "not-a-credential"}}, "api_fields"),
    ({"bodyTemplate": '{"ignored":true}'}, "api_fields"),
    ({"queryParamOverrides": {"property": "different"}}, "api_fields"),
    ({"onNotFound": "A separate not-found message"}, "speech"),
    ({"onAuthError": "A separate authorization message"}, "speech"),
    ({"retryCount": 1, "retryDelay": 1000}, "request_limits"),
])
def test_meaningful_unsupported_editor_controls_are_not_silently_discarded(changes, reason):
    config = editor_config()
    config["nodes"][2]["data"]["api"].update(changes)
    with pytest.raises(contract().PilotAdmissionError, match=reason):
        compile_graph(config)


def test_inherited_json_headers_do_not_become_caller_controlled_headers():
    compiled = compile_graph(editor_config())
    assert "headers" not in compiled.api_config()
    assert "bodyTemplate" not in compiled.api_config()
    assert "queryParamOverrides" not in compiled.api_config()


def test_explicit_llm_projection_survives_admission_without_rewriting_mappings():
    config = editor_config()
    config["nodes"][2]["data"]["api"]["responseProjection"] = {
        "fields": [{"variable": "rooms"}],
    }
    compiled = compile_graph(config)
    assert compiled.api_config()["responseProjection"] == {
        "fields": [{"variable": "rooms"}],
    }
    assert compiled.response_mappings == (("rooms", "$.rooms"), ("price", "$.rooms[0].price"))


@pytest.mark.parametrize("projection", [
    {"fields": [{"variable": "unknown"}]},
    {"fields": [{"variable": "price", "cleanup": ["eval"]}]},
])
def test_projection_is_validated_before_any_api_or_model_work(projection):
    config = editor_config()
    config["nodes"][2]["data"]["api"]["responseProjection"] = projection
    with pytest.raises(contract().PilotAdmissionError, match="projection"):
        compile_graph(config)


@pytest.mark.parametrize("field", ["globalPrompt", "systemPrompt", "retryPrompt", "maxRetries"])
def test_unsupported_instruction_or_retry_behavior_still_requires_explicit_support(field):
    config = editor_config()
    if field == "globalPrompt":
        config[field] = "Additional flow policy"
    elif field == "systemPrompt":
        config["nodes"][0]["data"][field] = "Additional start policy"
    else:
        config["nodes"][1]["data"]["slot"][field] = (
            "A different retry question" if field == "retryPrompt" else 3
        )
    with pytest.raises(contract().PilotAdmissionError):
        compile_graph(config)

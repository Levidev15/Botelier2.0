"""The editor must preview the real native mapping/projection, without I/O."""

import copy

import pytest


def preview(sample=None, configuration=None, variables=()):
    from botelier.services.flow_response_preview import preview_flow_response

    return preview_flow_response(
        {"hotel": {"name": "  <b>Harbor</b>  ", "rooms": [0, False, {"id": "suite"}]}}
        if sample is None else sample,
        {
            "responseMapping": {
                "hotel_name": "$.hotel.name", "rooms": "$.hotel.rooms",
            },
            "responseProjection": {
                "fields": [{"variable": "hotel_name", "cleanup": ["clean_text"]}],
            },
        } if configuration is None else configuration,
        variable_declarations=variables,
    )


def test_sample_preview_runs_the_identical_native_projection_and_keeps_raw_facts():
    result = preview()
    assert result["mapped_variables"] == {
        "hotel_name": "  <b>Harbor</b>  ", "rooms": [0, False, {"id": "suite"}],
    }
    assert result["llm_data"] == {"hotel_name": "Harbor"}


def test_preview_detaches_raw_sample_mapped_values_and_model_values():
    original = {"items": [{"id": "second", "total": "230.00"}]}
    before = copy.deepcopy(original)
    result = preview(original, {"responseMapping": {"rooms": "$.items"}})
    result["llm_data"]["rooms"][0]["id"] = "model-mutated"
    assert result["mapped_variables"]["rooms"][0]["id"] == "second"
    result["mapped_variables"]["rooms"][0]["id"] = "mapped-mutated"
    assert original == before


def test_inferred_outputs_have_the_same_optional_missing_semantics_as_native_graph():
    result = preview(
        {},
        {"responseMapping": {"optional_output": "$.absent"}},
    )
    assert result == {"mapped_variables": {}, "llm_data": {}}


def test_explicit_required_variables_fail_instead_of_showing_a_fake_model_result():
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    with pytest.raises(FlowResponsePreviewError, match=r"^mapping_required_output$"):
        preview(
            {},
            {"responseMapping": {"required_output": "$.absent"}},
            variables=[{"key": "required_output", "type": "text", "required": True}],
        )


def test_explicit_optional_legacy_text_variable_preserves_an_actual_json_array():
    result = preview(
        {"items": [0, False, {"room": "suite"}]},
        {"responseMapping": {"rooms": "$.items"}},
        variables=[{"key": "rooms", "type": "text", "required": False}],
    )
    assert result["llm_data"]["rooms"] == [0, False, {"room": "suite"}]


def test_response_variable_defaults_follow_the_actual_mapping_rules():
    result = preview(
        {"amount": 0, "accepted": False},
        {
            "responseVariables": [
                {"variableKey": "total", "jsonPath": "$.amount"},
                {"variableKey": "accepted", "jsonPath": "$.accepted"},
                {"variableKey": "unavailable", "jsonPath": "$.absent", "defaultValue": []},
            ],
            "responseProjection": {"fields": [
                {"variable": "total"}, {"variable": "accepted"},
            ]},
        },
    )
    assert result["mapped_variables"] == {
        "total": 0, "accepted": False, "unavailable": [],
    }
    assert result["llm_data"] == {"total": 0, "accepted": False}


@pytest.mark.parametrize(
    "projection",
    [
        {"fields": [{"variable": "missing"}]},
        {"fields": [{"variable": "hotel_name", "cleanup": ["eval"]}]},
        {"fields": [{"variable": "rooms", "cleanup": ["trim"]}]},
        {"fields": [{"variable": "hotel_name"}, {"variable": "hotel_name"}]},
    ],
)
def test_invalid_projection_cannot_be_advertised_as_the_model_payload(projection):
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    with pytest.raises(FlowResponsePreviewError, match=r"^mapping_projection$"):
        preview(configuration={
            "responseMapping": {"hotel_name": "$.hotel.name", "rooms": "$.hotel.rooms"},
            "responseProjection": projection,
        })


@pytest.mark.parametrize(
    "configuration",
    [
        {"url": "https://never-call.example.invalid", "responseMapping": {}},
        {"bodyTemplate": "secret-sensitive-test-only"},
        {"responseMapping": {"bad variable": "$.hotel"}},
        {"responseMapping": {"valid": 6}},
        {"responseMapping": []},
    ],
)
def test_preview_has_no_request_or_effect_configuration_surface(configuration):
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    with pytest.raises(FlowResponsePreviewError) as caught:
        preview(configuration=configuration)
    assert "secret-sensitive-test-only" not in str(caught.value)
    assert "never-call" not in str(caught.value)


@pytest.mark.parametrize(
    "variables",
    [
        [{"key": "rooms", "required": "false"}],
        [{"key": "rooms"}, {"key": "rooms"}],
        [{"key": "bad name"}],
        ["rooms"],
        {"rooms": {"required": False}},
    ],
)
def test_invalid_variable_metadata_is_rejected_without_coercion(variables):
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    with pytest.raises(FlowResponsePreviewError, match=r"^preview_declarations$"):
        preview(variables=variables)


@pytest.mark.parametrize("sample", [
    {"bad": float("nan")},
    {"bad": float("inf")},
    {1: "non-string-key"},
    {"object": object()},
    {"invalid_unicode": "\ud800"},
    {"private": "x" * 1_048_577},
])
def test_unbounded_or_non_json_samples_are_rejected_with_payload_free_errors(sample):
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    with pytest.raises(FlowResponsePreviewError) as caught:
        preview(sample)
    assert str(caught.value) in {"preview_sample", "preview_size"}
    assert "non-string-key" not in str(caught.value)


def test_cyclic_and_excessively_deep_samples_are_rejected_before_extraction():
    from botelier.services.flow_response_preview import FlowResponsePreviewError

    cycle = {}
    cycle["self"] = cycle
    deep = {}
    cursor = deep
    for _ in range(34):
        cursor["next"] = {}
        cursor = cursor["next"]
    for sample in [cycle, deep]:
        with pytest.raises(FlowResponsePreviewError, match=r"^preview_sample$"):
            preview(sample)


def test_empty_projection_really_sends_no_sample_fields_to_the_model():
    assert preview(
        {"quote": {"checkout_url": "https://review.example.invalid/synthetic-only"}},
        {
            "responseMapping": {"private_quote": "$.quote"},
            "responseProjection": {"fields": []},
        },
    )["llm_data"] == {}


@pytest.mark.parametrize("body", [
    b'{"sample":{},"sample":{},"configuration":{}}',
    b'{"sample":{"bad":NaN},"configuration":{}}',
    b'{"sample":{},"configuration":{},"execute":true}',
    b'[]',
    b'\xff',
])
def test_raw_envelope_is_strict_json_and_cannot_request_any_execution(body):
    from botelier.services.flow_response_preview import (
        FlowResponsePreviewError, preview_flow_response_json,
    )

    with pytest.raises(FlowResponsePreviewError) as caught:
        preview_flow_response_json(body)
    assert str(caught.value) in {"preview_json", "preview_request"}

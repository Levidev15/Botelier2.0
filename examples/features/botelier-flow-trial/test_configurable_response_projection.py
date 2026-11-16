"""The configured LLM data boundary must not rewrite authoritative facts."""

from copy import deepcopy

import pytest

from botelier.services import response_projection


def project(values, configuration=None):
    return response_projection.project_mapped_values(values, configuration)


def test_default_projection_keeps_original_json_values_and_array_identity():
    values = {
        "room_ids": ["standard", "suite"],
        "prices": ["100.00"],
        "available": False,
        "tax": 0,
        "missing": None,
        "description": "<p>Original description</p>",
    }
    assert project(values) == {
        "room_ids": ["standard", "suite"],
        "prices": ["100.00"],
        "available": False,
        "tax": 0,
        "missing": None,
        "description": "<p>Original description</p>",
    }


def test_explicit_projection_selects_and_cleans_only_the_configured_fields():
    values = {
        "rooms": [
            {"id": "standard", "total": "100.00"},
            {"id": "suite", "total": "251.2300"},
        ],
        "policy": "<p>  Tax &amp; fees are included. </p>",
        "internal_reference": "not-for-the-model",
    }
    before = deepcopy(values)
    configuration = {"fields": [
        {"variable": "rooms"},
        {"variable": "policy", "cleanup": ["clean_text"]},
    ]}
    assert project(values, configuration) == {
        "rooms": [
            {"id": "standard", "total": "100.00"},
            {"id": "suite", "total": "251.2300"},
        ],
        "policy": "Tax & fees are included.",
    }
    assert values == before
    assert configuration == {"fields": [
        {"variable": "rooms"},
        {"variable": "policy", "cleanup": ["clean_text"]},
    ]}


def test_projection_preview_cannot_mutate_internal_facts():
    values = {"rooms": [{"id": "suite", "price": "251.2300"}]}
    result = project(values, {"fields": [{"variable": "rooms"}]})
    result["rooms"][0]["id"] = "standard"
    assert values == {"rooms": [{"id": "suite", "price": "251.2300"}]}


@pytest.mark.parametrize("cleanup,expected", [
    (["trim"], "Tax \n  included"),
    (["collapse_whitespace"], " Tax included "),
    (["collapse_whitespace", "trim"], "Tax included"),
    (["clean_text"], "Tax included"),
])
def test_cleanup_is_an_explicit_bounded_operation_sequence(cleanup, expected):
    assert project(
        {"policy": "  Tax \n  included  "},
        {"fields": [{"variable": "policy", "cleanup": cleanup}]},
    ) == {"policy": expected}


@pytest.mark.parametrize("configuration", [
    [], "text", True,
    {"fields": "policy"},
    {"fields": [{"variable": "policy", "code": "value.upper()"}]},
    {"fields": [{"variable": "policy", "cleanup": ["eval"]}]},
    {"fields": [{"variable": "policy", "cleanup": "trim"}]},
    {"fields": [{"variable": "policy", "cleanup": ["trim"] * 4}]},
    {"fields": [{"variable": "policy"}, {"variable": "policy"}]},
    {"fields": [{"variable": "{{secrets.key}}"}]},
    {"fields": [{"variable": "policy"}], "prompt": "Invent a different price"},
])
def test_invalid_or_executable_projection_configuration_is_rejected(configuration):
    with pytest.raises(ValueError, match="projection"):
        project({"policy": "Original policy"}, configuration)


def test_missing_projection_source_is_not_invented():
    with pytest.raises(ValueError, match="projection_missing_variable"):
        project({"currency": "USD"}, {"fields": [{"variable": "total"}]})


@pytest.mark.parametrize("value", [None, False, 0, 125.5, [], {}])
def test_string_cleanup_cannot_coerce_or_recalculate_non_text_values(value):
    with pytest.raises(ValueError, match="projection_cleanup_type"):
        project({"total": value}, {"fields": [
            {"variable": "total", "cleanup": ["trim"]},
        ]})


def test_oversized_projection_fails_instead_of_silently_truncating_booking_facts():
    with pytest.raises(ValueError, match="projection_size"):
        project({"terms": "x" * 100_001})


def test_cleanup_work_is_bounded_before_processing_large_provider_text():
    with pytest.raises(ValueError, match="projection_size"):
        project({"terms": " " * 100_001}, {"fields": [
            {"variable": "terms", "cleanup": ["trim"]},
        ]})


def test_explicit_text_cleanup_handles_quoted_markup_without_leaking_attributes():
    assert project(
        {"terms": '<p title="Tax > zero">Taxes&nbsp; included.</p>'},
        {"fields": [{"variable": "terms", "cleanup": ["clean_text"]}]},
    ) == {"terms": "Taxes included."}


def test_non_json_values_and_non_finite_amounts_are_rejected():
    for value in (float("nan"), float("inf"), object()):
        with pytest.raises(ValueError, match="projection_json"):
            project({"total": value})


def test_structural_depth_is_bounded_without_flattening_records():
    value = {"id": "suite"}
    for _ in range(33):
        value = {"nested": value}
    with pytest.raises(ValueError, match="projection_depth"):
        project({"room": value})

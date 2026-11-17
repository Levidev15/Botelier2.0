"""Consumer contracts for validated native node values, not provider behavior."""

from copy import deepcopy
from datetime import date
import importlib
import importlib.util

import pytest


TODAY = date(2026, 11, 17)


def values():
    name = "botelier.voice.flows.native_values"
    assert importlib.util.find_spec(name) is not None, (
        "Native node value validation and deterministic rendering are missing"
    )
    return importlib.import_module(name)


def slot(kind="text", **config):
    return {"variableKey": "answer", "type": kind, "prompt": "Your answer?", **config}


@pytest.mark.parametrize("kind,raw,validation,want", [
    ("text", "  a room  ", {"minLength": 2, "maxLength": 12}, "a room"),
    ("number", "two", {"min": 1, "max": 3}, 2),
    ("number", "0", {"min": 0}, 0),
    ("number", "2.50", {"allowDecimal": True}, 2.5),
    ("email", " Guest@Example.Test ", {}, "guest@example.test"),
    ("phone", "(212) 555-0100", {}, "+12125550100"),
    ("phone", "+44 20 7946 0100", {}, "+442079460100"),
    ("date", "2026-11-19", {"minDaysAhead": 2, "maxDaysAhead": 30}, "2026-11-19"),
    ("date", "tomorrow", {}, "2026-11-18"),
    ("date", "2020-01-01", {"requireFuture": False}, "2020-01-01"),
    ("time", "3:30 pm", {}, "15:30"),
    ("time", "00:00", {}, "00:00"),
    ("choice", "  SuITE ", {"choices": ["Standard", "Suite"]}, "Suite"),
    ("text", "AB12", {"pattern": "^[A-Z]{2}[0-9]{2}$"}, "AB12"),
])
def test_current_slot_types_normalize_without_changing_meaning(kind, raw, validation, want):
    assert values().validate_value(
        slot(kind, validation=validation), raw, {}, today=TODAY,
    ) == want


@pytest.mark.parametrize("kind,raw,validation", [
    ("text", "", {}),
    ("text", {"content": "not text"}, {}),
    ("text", "short", {"minLength": 10}),
    ("text", "overlong", {"maxLength": 3}),
    ("text", "wrong", {"pattern": "^[0-9]{4}$"}),
    ("number", True, {}),
    ("number", "NaN", {"allowDecimal": True}),
    ("number", float("inf"), {"allowDecimal": True}),
    ("number", "1.5", {}),
    ("number", 0, {"min": 1}),
    ("number", 11, {"max": 10}),
    ("email", "victim@example.test\r\nBcc:other@example.test", {}),
    ("email", "Not An Address <guest@example.test>", {}),
    ("phone", "words +12125550100 extension 7", {}),
    ("date", "2026-02-30", {}),
    ("date", "2026-11-16", {}),
    ("date", "2026-11-18", {"minDaysAhead": 2}),
    ("date", "2027-01-01", {"maxDaysAhead": 10}),
    ("time", "25:00", {}),
    ("time", "15 pm", {}),
    ("choice", "room", {"choices": ["Standard room", "Suite room"]}),
    ("choice", "unknown", {"choices": ["Standard", "Suite"]}),
])
def test_invalid_untrusted_slot_values_are_rejected_with_safe_categories(kind, raw, validation):
    with pytest.raises(values().NativeValueError) as error:
        values().validate_value(slot(kind, validation=validation), raw, {}, today=TODAY)
    assert str(error.value).startswith("slot_")
    assert "Bcc" not in str(error.value)


def test_cross_field_checks_use_current_facts_and_fail_when_the_dependency_is_invalid():
    api = values()
    config = slot("date", validation={
        "crossFieldCheck": {"compareWith": "arrival", "operator": "after"},
    })
    assert api.validate_value(config, "2026-11-20", {"arrival": "2026-11-19"}, today=TODAY) == "2026-11-20"
    for facts in ({"arrival": "2026-11-20"}, {"arrival": "corrupt"}, {}):
        with pytest.raises(api.NativeValueError, match="slot_cross_field"):
            api.validate_value(config, "2026-11-20", facts, today=TODAY)
    numeric = slot("number", validation={
        "crossFieldCheck": {"compareWith": "minimum", "operator": "greater"},
    })
    assert api.validate_value(numeric, 3, {"minimum": 2}, today=TODAY) == 3
    with pytest.raises(api.NativeValueError, match="slot_cross_field"):
        api.validate_value(numeric, 2, {"minimum": 2}, today=TODAY)


def test_regex_matching_has_a_work_budget_for_an_adversarial_response():
    with pytest.raises(values().NativeValueError, match="slot_pattern"):
        values().validate_value(
            slot("text", validation={"pattern": r"(a+)+$", "maxLength": 3000}),
            "a" * 2000 + "!", {}, today=TODAY,
        )


def test_explicitly_disabled_builtin_normalization_does_not_disable_type_or_configured_limits():
    api = values()
    assert api.validate_value(slot("phone", useBuiltInValidator=False), "212-555-0100", {}, today=TODAY) == "212-555-0100"
    with pytest.raises(api.NativeValueError, match="slot_"):
        api.validate_value(slot("text", useBuiltInValidator=False, validation={"maxLength": 3}), "longer", {}, today=TODAY)


def test_templates_preserve_zero_false_and_scoped_named_data_without_dumping_json_to_tts():
    api = values()
    facts = {"amount": 0, "available": False, "rooms": [{"name": "<b>Suite</b>", "secret": "never-spoken"}, {"name": "Twin"}]}
    assert api.render_text("Amount {{amount}}, available {{available}}.", facts) == "Amount 0, available false."
    assert api.render_text("Options: {{rooms}}.", facts) == "Options: Suite and Twin."
    assert api.render_text("{{rooms}}", facts, speech=False) == '[{"name":"<b>Suite</b>","secret":"never-spoken"},{"name":"Twin"}]'
    with pytest.raises(api.NativeValueError, match="template_missing"):
        api.render_text("{{missing}}", facts)
    with pytest.raises(api.NativeValueError, match="template_"):
        api.render_text("{{amount.__class__}}", facts)


@pytest.mark.parametrize("operator,actual,expected,want", [
    ("equals", " Suite ", "suite", True),
    ("not_equals", "Suite", "Twin", True),
    ("contains", "Garden Suite", "suite", True),
    ("greater_than", "12.50", "2.20", True),
    ("less_than", 0, 1, True),
    ("greater_than", "2026-12-01", "2026-11-30", True),
    ("is_empty", [], "", True),
    ("is_empty", 0, "", False),
    ("is_empty", False, "", False),
    ("is_not_empty", {"id": "offer"}, "", True),
])
def test_condition_operators_are_deterministic_and_do_not_turn_zero_into_missing(operator, actual, expected, want):
    assert values().evaluate_condition(
        {"variable": "value", "operator": operator, "value": expected},
        {"value": actual},
    ) is want


def test_configured_value_operations_are_bounded_and_never_execute_code():
    api = values()
    facts = {"count": 2, "extra": 3, "name": "Suite"}
    assert api.evaluate_value({"valueType": "static", "value": "0"}, facts) == "0"
    assert api.evaluate_value({"valueType": "template", "value": "{{name}} / {{count}}"}, facts) == "Suite / 2"
    assert api.evaluate_value({"valueType": "expression", "value": "count + extra * 2"}, facts) == 8
    assert api.evaluate_value({"valueType": "expression", "value": "count if count > 0 else 1"}, facts) == 2
    assert api.evaluate_value({"valueType": "expression", "value": "'x' * count"}, facts) == "xx"
    for expression in (
        "__import__('os').system('true')", "count.__class__", "1 / 0",
        "2 ** 99999999", "'x' * 999999999", "unknown + 1", "count[0]",
    ):
        with pytest.raises(api.NativeValueError, match="expression_"):
            api.evaluate_value({"valueType": "expression", "value": expression}, facts)


def test_nonfirst_option_atomically_binds_every_configured_write_without_mutating_the_source():
    api = values()
    facts = {"offers": [
        {"name": "Twin", "room": {"id": "room-twin"}, "rate": "refundable", "total": "100.00"},
        {"name": "Suite", "room": {"id": "room-suite"}, "total": "150.00"},
    ]}
    before = deepcopy(facts)
    config = {
        "sourceVariable": "offers", "labelPath": "name",
        "writes": [
            {"variableKey": "room_id", "path": "room.id"},
            {"variableKey": "rate", "path": "rate"},
            {"variableKey": "total", "path": "total"},
        ],
    }
    selected = api.resolve_option(config, facts, {"ordinal": 2})
    assert selected.index == 1
    assert selected.label == "Suite"
    assert selected.writes == {"room_id": "room-suite", "rate": None, "total": "150.00"}
    assert facts == before
    selected.writes["room_id"] = "consumer edit"
    assert facts == before


@pytest.mark.parametrize("arguments", [
    {"ordinal": True}, {"ordinal": 1.5}, {"ordinal": 99},
    {"ordinal": 2, "label": "Twin"}, {"label": "room"}, {},
    {"label": "Suite", "write": {"room_id": "forged"}},
])
def test_option_selection_does_not_guess_accept_extra_args_or_truncate_ordinals(arguments):
    api = values()
    config = {"sourceVariable": "offers", "labelPath": "name", "writes": [{"variableKey": "room_id", "path": "id"}]}
    facts = {"offers": [{"name": "Twin room", "id": "twin"}, {"name": "Suite room", "id": "suite"}]}
    with pytest.raises(api.NativeValueError, match="selection_"):
        api.resolve_option(config, facts, arguments)


def test_response_presentation_uses_configured_fields_once_and_preserves_zero_prices():
    api = values()
    config = {
        "arrayVariable": "offers", "introText": "Rooms:",
        "itemTemplate": "{{index}}: {{name}} {{total}}.",
        "outroText": "Which room?", "noResultsText": "Nothing available.",
    }
    assert api.present_response(config, {"offers": [{"name": "Suite", "total": 0}]}) == (
        "Rooms: 1: Suite 0. Which room?", True,
    )
    assert api.present_response(config, {"offers": []}) == ("Nothing available.", False)
    assert api.present_response({"introText": "Checked.", "outroText": "Continue."}, {}) == ("Checked. Continue.", True)
    with pytest.raises(api.NativeValueError, match="presentation_"):
        api.present_response(config, {"offers": {"not": "an array"}})
    with pytest.raises(api.NativeValueError, match="presentation_"):
        api.present_response(config, {"offers": [{"name": "missing amount"}]})


def test_builtin_date_defaults_and_day_first_format_match_the_existing_validator_contract():
    api = values()
    assert api.validate_value(slot("date"), "20/11/2026", {}, today=TODAY) == "2026-11-20"
    with pytest.raises(api.NativeValueError, match="slot_date_max"):
        api.validate_value(slot("date"), "2028-01-01", {}, today=TODAY)
    assert api.validate_value(
        slot("date", validation={"maxDaysAhead": 800}), "2028-01-01", {}, today=TODAY,
    ) == "2028-01-01"


def test_builtin_text_default_is_500_without_weakening_explicit_or_disabled_settings():
    api = values()
    with pytest.raises(api.NativeValueError, match="slot_length"):
        api.validate_value(slot("text"), "a" * 501, {}, today=TODAY)
    assert len(api.validate_value(
        slot("text", validation={"maxLength": 700}), "a" * 501, {}, today=TODAY,
    )) == 501
    assert len(api.validate_value(
        slot("text", useBuiltInValidator=False), "a" * 501, {}, today=TODAY,
    )) == 501


@pytest.mark.parametrize("pattern", [123, {"pattern": "x"}, "x" + "(?:)" * 129])
def test_untrusted_pattern_configuration_is_bounded_before_regex_compilation(pattern):
    with pytest.raises(values().NativeValueError, match="slot_pattern"):
        values().validate_value(slot("text", validation={"pattern": pattern}), "x", {}, today=TODAY)


def test_unknown_cross_field_operator_is_not_interpreted_as_before():
    with pytest.raises(values().NativeValueError, match="slot_cross_field"):
        values().validate_value(
            slot("number", validation={"crossFieldCheck": {"compareWith": "minimum", "operator": "typo"}}),
            1, {"minimum": 2}, today=TODAY,
        )


def test_outsize_integers_are_rejected_as_safe_template_and_presentation_errors():
    api = values()
    huge = 10 ** 1500
    with pytest.raises(api.NativeValueError, match="template_"):
        api.render_text("{{amount}}", {"amount": huge})
    with pytest.raises(api.NativeValueError, match="presentation_"):
        api.present_response(
            {"arrayVariable": "offers", "itemTemplate": "{{amount}}"},
            {"offers": [{"amount": huge}]},
        )

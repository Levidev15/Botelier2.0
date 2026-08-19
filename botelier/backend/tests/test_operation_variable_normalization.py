from botelier.services.operation_publisher import (
    _build_llm_input_schema,
    normalize_operation_variables,
)


def test_normalizes_certified_seed_variable_shape_without_losing_legacy_key():
    variables = normalize_operation_variables(
        [
            {
                "key": "check_in_date",
                "label": "Check-in Date",
                "type": "date",
                "required": True,
            }
        ]
    )

    assert variables == [
        {
            "key": "check_in_date",
            "name": "check_in_date",
            "label": "Check-in Date",
            "description": "Check-in Date",
            "type": "date",
            "required": True,
        }
    ]


def test_preserves_imported_spec_shape_and_prefers_explicit_description():
    variables = normalize_operation_variables(
        [
            {
                "name": "guest_count",
                "description": "Adults",
                "label": "Ignored fallback",
                "type": "number",
            }
        ]
    )

    assert variables[0]["name"] == "guest_count"
    assert variables[0]["key"] == "guest_count"
    assert variables[0]["description"] == "Adults"


def test_llm_schema_supports_certified_seed_variables():
    schema = _build_llm_input_schema(
        [
            {
                "key": "check_out_date",
                "label": "Check-out Date",
                "type": "date",
                "required": True,
            }
        ]
    )

    assert schema["properties"]["check_out_date"] == {
        "type": "date",
        "description": "Check-out Date",
    }
    assert schema["required"] == ["check_out_date"]


def test_drops_variables_without_any_identifier():
    assert normalize_operation_variables([{"type": "string"}, None]) == []
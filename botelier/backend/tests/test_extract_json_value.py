"""Unit tests for the shared JSONPath-lite extractor.

``extract_json_value`` is the single source of truth used by both
``IntegrationClient`` and ``flow_executor`` to resolve response-mapping paths,
so its behaviour is covered here in isolation.
"""

from datetime import datetime

from botelier.services.integration_client import IntegrationClient, extract_json_value


def test_returns_data_for_empty_path():
    data = {"a": 1}
    assert extract_json_value(data, "") is data
    assert extract_json_value(data, None) is data


def test_root_prefix_is_optional():
    data = {"a": {"b": "x"}}
    assert extract_json_value(data, "a.b") == "x"
    assert extract_json_value(data, "$a.b") == "x"
    assert extract_json_value(data, "$.a.b") == "x"


def test_dot_keys():
    data = {"a": {"b": {"c": 42}}}
    assert extract_json_value(data, "a.b.c") == 42


def test_bracket_index():
    data = {"items": [{"id": "first"}, {"id": "second"}]}
    assert extract_json_value(data, "items[0].id") == "first"
    assert extract_json_value(data, "items[1].id") == "second"


def test_legacy_dot_index():
    data = {"items": [{"id": "first"}, {"id": "second"}]}
    assert extract_json_value(data, "items.0.id") == "first"
    assert extract_json_value(data, "$.items.1.id") == "second"


def test_missing_path_returns_none():
    data = {"a": {"b": 1}}
    assert extract_json_value(data, "a.x") is None
    assert extract_json_value(data, "a.b.c.d") is None
    assert extract_json_value(data, "items[5].id") is None


def test_wildcard_flattens_and_dedupes_preserving_order():
    data = {
        "hotelAvailability": [
            {
                "roomStays": [
                    {
                        "roomRates": [
                            {"roomType": "DLX"},
                            {"roomType": "STD"},
                        ]
                    }
                ]
            },
            {
                "roomStays": [
                    {
                        "roomRates": [
                            {"roomType": "STD"},
                            {"roomType": "SUITE"},
                        ]
                    }
                ]
            },
        ]
    }
    result = extract_json_value(
        data, "$.hotelAvailability[*].roomStays[*].roomRates[*].roomType"
    )
    assert result == ["DLX", "STD", "SUITE"]


def test_wildcard_returns_none_when_empty():
    data = {"hotelAvailability": []}
    assert (
        extract_json_value(
            data, "$.hotelAvailability[*].roomStays[*].roomRates[*].roomType"
        )
        is None
    )


def test_wildcard_skips_non_list_nodes():
    data = {"hotelAvailability": {"not": "a list"}}
    assert extract_json_value(data, "$.hotelAvailability[*].roomType") is None


def test_non_wildcard_returns_scalar_not_list():
    data = {"reservations": {"reservationInfo": [{"id": "R1"}]}}
    assert (
        extract_json_value(data, "$.reservations.reservationInfo[0].id") == "R1"
    )


def test_array_value_returned_whole_without_wildcard():
    data = {"reservations": {"reservationInfo": [{"id": "R1"}, {"id": "R2"}]}}
    assert extract_json_value(data, "$.reservations.reservationInfo") == [
        {"id": "R1"},
        {"id": "R2"},
    ]


def _client():
    return IntegrationClient(account_id="00000000-0000-0000-0000-000000000001")


def test_today_default_resolves_to_current_date():
    endpoint_def = {
        "variables": [{"key": "date", "type": "date", "default": "today"}]
    }
    merged = _client()._apply_endpoint_defaults({}, endpoint_def)
    assert merged["date"] == datetime.utcnow().date().isoformat()


def test_caller_value_overrides_today_default():
    endpoint_def = {
        "variables": [{"key": "date", "type": "date", "default": "today"}]
    }
    merged = _client()._apply_endpoint_defaults({"date": "2030-01-15"}, endpoint_def)
    assert merged["date"] == "2030-01-15"


def test_static_defaults_applied_and_overridable():
    endpoint_def = {
        "variables": [
            {"key": "guest_count", "type": "number", "default": 1},
            {"key": "child_count", "type": "number", "default": 0},
        ]
    }
    merged = _client()._apply_endpoint_defaults({"guest_count": 3}, endpoint_def)
    assert merged["guest_count"] == 3
    assert merged["child_count"] == 0

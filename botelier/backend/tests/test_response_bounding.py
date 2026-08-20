import json

from botelier.services.integration_runtime.redaction import (
    bound_and_redact_response,
)


def test_large_nested_array_keeps_useful_prefix_instead_of_only_marker():
    data = {
        "roomTypes": [
            {"code": f"ROOM-{index}", "description": "x" * 80}
            for index in range(100)
        ],
        "links": [{"rel": "self"}],
    }

    bounded, warnings = bound_and_redact_response(
        data, {"size_limit_bytes": 500}
    )

    assert bounded["roomTypes"]
    assert bounded["roomTypes"][0]["code"] == "ROOM-0"
    assert bounded["__truncated__"] is True
    assert len(json.dumps(bounded)) <= 500
    assert any("truncated" in warning for warning in warnings)


def test_large_nested_dictionary_preserves_first_nested_fields():
    data = {
        "payload": {
            "hotelId": "OHIPSB02",
            "rates": [{"code": f"RATE-{index}", "text": "y" * 60} for index in range(50)],
        }
    }

    bounded, _ = bound_and_redact_response(data, {"size_limit_bytes": 400})

    assert bounded["payload"]["hotelId"] == "OHIPSB02"
    assert bounded["payload"]["rates"]
    assert len(json.dumps(bounded)) <= 400


def test_small_response_is_unchanged():
    data = {"roomTypes": [{"code": "KING"}]}
    bounded, warnings = bound_and_redact_response(data, {"size_limit_bytes": 500})
    assert bounded == data
    assert warnings == []


def test_redaction_still_happens_before_recursive_bounding():
    data = {
        "items": [
            {"code": str(index), "card_number": "4111111111111111", "text": "z" * 50}
            for index in range(30)
        ]
    }
    bounded, _ = bound_and_redact_response(data, {"size_limit_bytes": 350})

    assert bounded["items"][0]["card_number"] == "[REDACTED]"
    assert "4111111111111111" not in json.dumps(bounded)
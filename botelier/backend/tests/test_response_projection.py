"""Tests for the display-only mapped-response projection."""

from botelier.services.response_projection import format_mapped_response
from botelier.flow_executor import _build_api_voice_result


def test_parallel_arrays_are_joined_by_index_and_keep_missing_tail_data():
    projection = format_mapped_response(
        {
            "cancellation_id": [9999, 10000, 10001, 10002, 10003],
            "cancellation_name": [
                "Non-refundable",
                "48 Hours",
                "Fully flexible",
                "non refundable",
                "Flexible Cancelation",
            ],
            "cancellation_rules": [
                [{"value": 100, "type": "Percentage", "text": "Non refundable"}],
                [{"value": 1, "type": "Amount", "text": "Charged 1 night"}],
                [],
                [{"value": 100, "type": "Percentage", "text": "Charged 100%"}],
            ],
            "cancellation_policies_text": ["", "<p>48 hours</p>"],
        }
    )

    assert "Results:\n\n1." in projection
    assert "   Cancellation id: 9999\n   Cancellation name: Non-refundable" in projection
    assert (
        "   Cancellation rules:\n"
        "     - Value: 100\n"
        "       Type: Percentage\n"
        "       Text: Non refundable"
    ) in projection
    assert "   Cancellation policies text: 48 hours" in projection
    assert "\n\n5.\n   Cancellation id: 10003\n   Cancellation name: Flexible Cancelation" in projection


def test_regular_values_and_single_arrays_remain_readable():
    projection = format_mapped_response(
        {
            "hotel_name": "Harbor <strong>House</strong>",
            "available_rooms": ["King", "Suite"],
        }
    )

    assert "Available rooms:\n   - King\n   - Suite" in projection
    assert "Shared data:\n   Hotel name: Harbor House" in projection


def test_nested_objects_are_readable_without_json_syntax():
    projection = format_mapped_response(
        {
            "policy": {
                "name": "Flexible",
                "rule": {"before_days": 2, "text": "No fee"},
            }
        }
    )

    assert projection == (
        "Policy:\n"
        "   Name: Flexible\n"
        "   Rule:\n"
        "      Before days: 2\n"
        "      Text: No fee"
    )
    assert "{" not in projection


def test_llm_fallback_uses_the_same_mapped_response_projection():
    result = _build_api_voice_result(
        "Cancellation policies found",
        {
            "cancellation_id": [9999, 10003],
            "cancellation_name": ["Non-refundable", "Flexible Cancelation"],
            "cancellation_rules": [[{"text": "Non refundable"}]],
        },
    )

    assert result.startswith("Cancellation policies found.\nResults:\n\n1.")
    assert "1.\n   Cancellation id: 9999\n   Cancellation name: Non-refundable" in result
    assert (
        "2.\n   Cancellation id: 10003\n   Cancellation name: Flexible Cancelation"
    ) in result
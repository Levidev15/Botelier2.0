"""Pure output-only JSON values retain their real types and stay bounded."""

import math

import pytest


def test_output_json_copy_is_detached_without_losing_zero_false_or_arrays():
    from botelier.voice.flows.native_execution import copy_native_json

    original = [{"total": 0, "tax_inclusive": False, "details": {"currency": "USD"}}]
    copied = copy_native_json(original)
    copied[0]["details"]["currency"] = "EUR"
    assert original == [{"total": 0, "tax_inclusive": False, "details": {"currency": "USD"}}]
    assert copied[0]["total"] == 0 and copied[0]["tax_inclusive"] is False


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, object(), "x" * 260_000],
    ids=["nan", "infinity", "non-json", "too-large"],
)
def test_output_json_rejects_non_json_non_finite_and_oversized_values(value):
    from botelier.voice.flows.native_execution import copy_native_json

    with pytest.raises(ValueError, match="native_json_value"):
        copy_native_json(value)

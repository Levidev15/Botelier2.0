"""Offline acceptance of provider-authoritative, noncharging quote/link data."""

from datetime import datetime, timezone
import math

import pytest


NOW = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
ORIGINS = ("https://booking.example.invalid",)


def quote_data():
    return {
        "quote_id": "quote-suite-2",
        "room_id": "suite",
        "rate_id": "flexible",
        "check_in": "2026-12-01",
        "check_out": "2026-12-03",
        "adults": 2,
        "children": 0,
        "pricing": {
            "basis": "stay", "currency": "USD",
            "subtotal": "200.00", "tax_total": "20.00",
            "fees_total": "10.00", "tax_treatment": "exclusive",
            "fees_treatment": "exclusive", "total": "230.00",
        },
        "expires_at": "2026-12-01T15:10:00Z",
        "checkout_url": (
            "https://booking.example.invalid/review/quote-suite-2"
            "?session=synthetic-test-only"
        ),
    }


def selected():
    return {
        "room_id": "suite", "rate_id": "flexible",
        "check_in": "2026-12-01", "check_out": "2026-12-03",
        "adults": 2, "children": 0, "currency": "USD",
    }


def validate(value=None, **kwargs):
    from botelier.services.reservation_quote_contract import validate_reservation_quote

    return validate_reservation_quote(
        quote_data() if value is None else value,
        expected=kwargs.pop("expected", selected()),
        allowed_checkout_origins=kwargs.pop("allowed_checkout_origins", ORIGINS),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def assert_invalid(value, code, **kwargs):
    from botelier.services.reservation_quote_contract import QuoteContractError

    with pytest.raises(QuoteContractError) as caught:
        validate(value, **kwargs)
    assert caught.value.code == code
    assert "synthetic-test-only" not in str(caught.value)
    return caught.value


def test_preserves_authoritative_values_and_detaches_the_verified_snapshot():
    original = quote_data()
    result = validate(original, require_checkout_link=True)
    assert result.data() == original
    assert len(result.fingerprint) == 64
    first = result.data()
    first["pricing"]["total"] = "0.00"
    original["pricing"]["total"] = "1.00"
    assert result.data()["pricing"]["total"] == "230.00"
    assert result.data()["children"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("room_id", "first-room-not-the-selected-suite"),
        ("rate_id", "nonrefundable"),
        ("check_in", "2026-12-02"),
        ("check_out", "2026-12-04"),
        ("adults", 3),
        ("children", 1),
    ],
)
def test_rejects_another_room_rate_stay_or_guest_count(field, value):
    quote = quote_data()
    quote[field] = value
    assert_invalid(quote, "selection_mismatch")


@pytest.mark.parametrize("field", ["subtotal", "tax_total", "fees_total", "total"])
def test_never_fills_missing_required_amounts_with_zero(field):
    quote = quote_data()
    del quote["pricing"][field]
    error = assert_invalid(quote, "pricing_required")
    assert error.path == f"pricing.{field}"


@pytest.mark.parametrize("value", [None, True, -1, "NaN", math.inf, "1,000.00"])
def test_rejects_ambiguous_or_nonfinite_money_without_guessing(value):
    quote = quote_data()
    quote["pricing"]["total"] = value
    assert_invalid(quote, "money")


def test_zero_is_a_real_quote_value_not_a_missing_value():
    quote = quote_data()
    quote["pricing"].update({
        "subtotal": 0, "tax_total": 0, "fees_total": 0, "total": 0,
        "tax_treatment": "none", "fees_treatment": "none",
    })
    result = validate(quote)
    assert result.data()["pricing"]["total"] == 0


@pytest.mark.parametrize("field", ["tax_treatment", "fees_treatment"])
def test_unknown_treatment_is_not_assumed_inclusive(field):
    quote = quote_data()
    quote["pricing"][field] = "unknown"
    assert_invalid(quote, "pricing_treatment")


def test_must_not_confuse_a_nightly_price_with_the_stay_total():
    quote = quote_data()
    quote["pricing"]["basis"] = "night"
    assert_invalid(quote, "pricing_basis")


def test_inconsistent_total_is_rejected_not_recalculated():
    quote = quote_data()
    quote["pricing"]["total"] = "999.00"
    assert_invalid(quote, "pricing_inconsistent")
    assert quote["pricing"]["total"] == "999.00"


def test_inclusive_tax_is_not_added_twice():
    quote = quote_data()
    quote["pricing"].update({
        "subtotal": "220.00", "tax_treatment": "inclusive",
    })
    assert validate(quote).data()["pricing"]["total"] == "230.00"


def test_mixed_tax_requires_and_checks_the_included_and_excluded_lines():
    quote = quote_data()
    quote["pricing"].update({
        "subtotal": "212.00", "tax_treatment": "mixed",
        "tax_lines": [
            {"name": "VAT", "amount": "12.00", "currency": "USD", "included": True},
            {"name": "Local tax", "amount": "8.00", "currency": "USD", "included": False},
        ],
    })
    assert validate(quote).data()["pricing"]["total"] == "230.00"
    del quote["pricing"]["tax_lines"]
    assert_invalid(quote, "pricing_lines")


def test_currency_mismatch_in_totals_or_components_is_not_converted():
    quote = quote_data()
    quote["pricing"]["currency"] = "EUR"
    assert_invalid(quote, "currency_mismatch")
    quote = quote_data()
    quote["pricing"]["tax_lines"] = [
        {"name": "Tax", "amount": "20.00", "currency": "EUR", "included": False},
    ]
    assert_invalid(quote, "currency_mismatch")


@pytest.mark.parametrize(
    "currency,subtotal,tax,fees,total",
    [
        ("JPY", 200, 20, 10, 230),
        ("BHD", "200.000", "20.001", "10.000", "230.001"),
    ],
)
def test_currency_precision_is_preserved(currency, subtotal, tax, fees, total):
    quote = quote_data()
    quote["pricing"].update({
        "currency": currency, "subtotal": subtotal, "tax_total": tax,
        "fees_total": fees, "total": total,
    })
    expected = selected()
    expected["currency"] = currency
    assert validate(quote, expected=expected).data()["pricing"]["total"] == total


def test_fractional_minor_units_are_not_silently_rounded():
    quote = quote_data()
    quote["pricing"]["total"] = "230.001"
    assert_invalid(quote, "money_precision")


@pytest.mark.parametrize(
    "expiry", ["2026-12-01T14:59:59Z", "2026-12-01T15:00:00Z"],
)
def test_expired_quote_cannot_prepare_a_link(expiry):
    quote = quote_data()
    quote["expires_at"] = expiry
    assert_invalid(quote, "quote_expired", require_checkout_link=True)


def test_timezone_is_required_and_offset_is_compared_as_an_instant():
    quote = quote_data()
    quote["expires_at"] = "2026-12-01T10:10:00-05:00"
    assert validate(quote).data()["expires_at"].endswith("-05:00")
    quote["expires_at"] = "2026-12-01T15:10:00"
    assert_invalid(quote, "quote_expiry")


def test_no_expiry_reported_does_not_invent_an_expiration_date():
    quote = quote_data()
    del quote["expires_at"]
    assert "expires_at" not in validate(quote).data()


@pytest.mark.parametrize(
    "url",
    [
        "http://booking.example.invalid/review/test",
        "javascript:alert(1)",
        "https://unapproved.example.invalid/review/test",
        "https://user:password@booking.example.invalid/review/test",
        "https://booking.example.invalid.evil.invalid/review/test",
        "https://booking.example.invalid/review/\nnot-a-valid-link",
        "https://booking.example.invalid/review/\u202econceled-link",
    ],
)
def test_rejects_unsafe_or_unapproved_review_links(url):
    quote = quote_data()
    quote["checkout_url"] = url
    assert_invalid(quote, "checkout_link", require_checkout_link=True)


def test_links_are_optional_during_quotation_but_required_before_delivery():
    quote = quote_data()
    del quote["checkout_url"]
    assert validate(quote).data() == quote
    assert_invalid(quote, "checkout_link", require_checkout_link=True)


@pytest.mark.parametrize("host", ["127.0.0.1", "0x7f.0.0.1", "0177.0.0.1"])
def test_link_policy_cannot_approve_private_hosts_or_credentials(host):
    quote = quote_data()
    quote["checkout_url"] = f"https://{host}/review/test"
    assert_invalid(
        quote, "checkout_origin",
        allowed_checkout_origins=(f"https://{host}",),
    )


def test_a_price_or_selection_change_invalidates_the_confirmed_fingerprint():
    previous = validate()
    quote = quote_data()
    quote["pricing"].update({"subtotal": "210.00", "total": "240.00"})
    assert_invalid(quote, "quote_changed", confirmed_fingerprint=previous.fingerprint)
    assert validate(quote).fingerprint != previous.fingerprint


def test_generating_a_new_link_does_not_change_the_confirmed_price_snapshot():
    previous = validate()
    quote = quote_data()
    quote["checkout_url"] = "https://booking.example.invalid/review/new-synthetic-session"
    assert validate(quote, confirmed_fingerprint=previous.fingerprint).fingerprint == previous.fingerprint


def test_validation_errors_do_not_expose_raw_provider_values_or_links():
    quote = quote_data()
    quote["pricing"]["total"] = "private-provider-value"
    error = assert_invalid(quote, "money")
    assert "private-provider-value" not in str(error)


def test_bounded_payload_rejects_unconfigured_provider_fields():
    quote = quote_data()
    quote["private_guest_note"] = "not approved for this pricing contract"
    assert_invalid(quote, "quote_fields")


def test_snapshot_uses_no_user_defined_serializers_or_unbounded_recursive_data():
    quote = quote_data()
    quote["pricing"]["tax_lines"] = [quote]
    assert_invalid(quote, "quote_payload")


def test_model_projection_never_contains_the_bearer_link():
    result = validate(require_checkout_link=True)
    visible = result.model_data()
    assert visible["checkout_link_available"] is True
    assert "checkout_url" not in visible
    assert "synthetic-test-only" not in repr(visible)
    assert result.data()["checkout_url"].endswith("session=synthetic-test-only")


def test_due_now_and_pay_at_property_are_not_replaced_with_the_stay_total():
    quote = quote_data()
    quote["pricing"].update({"due_now": "50.00", "pay_at_property": "180.00"})
    result = validate(quote)
    assert result.data()["pricing"]["due_now"] == "50.00"
    assert result.data()["pricing"]["pay_at_property"] == "180.00"
    assert result.data()["pricing"]["total"] == "230.00"
    quote["pricing"]["pay_at_property"] = "230.00"
    assert_invalid(quote, "pricing_inconsistent")


def test_boolean_false_does_not_impersonate_a_zero_child_count():
    quote = quote_data()
    quote["children"] = False
    assert_invalid(quote, "quote_identity")


def test_selected_rate_cannot_be_accidentally_omitted_from_expected_binding():
    expected = selected()
    del expected["rate_id"]
    error = assert_invalid(quote_data(), "selection_required", expected=expected)
    assert error.path == "expected.rate_id"


def test_provider_assigned_rate_requires_explicit_policy_and_is_still_fingerprinted():
    expected = selected()
    del expected["rate_id"]
    policy = {"expected": expected, "provider_selected_dimensions": ("rate_id",)}
    result = validate(**policy)
    quote = quote_data()
    quote["rate_id"] = "different-provider-assigned-rate"
    assert_invalid(
        quote, "quote_changed", confirmed_fingerprint=result.fingerprint, **policy,
    )


@pytest.mark.parametrize("dimension", ["offer_id", "hotel_id"])
def test_reported_selection_dimensions_must_not_be_silently_unbound(dimension):
    quote = quote_data()
    quote[dimension] = "provider-dimension"
    error = assert_invalid(quote, "selection_required")
    assert error.path == f"expected.{dimension}"
    expected = selected()
    expected[dimension] = "provider-dimension"
    assert validate(quote, expected=expected).data()[dimension] == "provider-dimension"


def test_property_identity_cannot_be_waived_as_a_provider_selected_dimension():
    assert_invalid(
        quote_data(), "selection_policy",
        provider_selected_dimensions=("hotel_id",),
    )


@pytest.mark.parametrize("dimension", ["room_id", "rate_id"])
def test_opaque_numeric_provider_ids_are_preserved_and_match_without_loss(dimension):
    quote = quote_data()
    quote[dimension] = 42
    expected = selected()
    expected[dimension] = 42
    assert validate(quote, expected=expected).data()[dimension] == 42
    expected[dimension] = "42"
    assert validate(quote, expected=expected).data()[dimension] == 42
    quote[dimension] = "042"
    assert_invalid(quote, "selection_mismatch", expected=expected)


def test_uyi_uses_zero_minor_units_instead_of_defaulting_to_two():
    quote = quote_data()
    quote["pricing"].update({
        "currency": "UYI", "subtotal": "200.50", "total": "230.50",
    })
    expected = selected()
    expected["currency"] = "UYI"
    assert_invalid(quote, "money_precision", expected=expected)

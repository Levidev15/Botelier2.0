"""Pure native quote preparation; actual broker/SDK wiring is a separate gate."""

from copy import deepcopy
from datetime import timedelta
import json

import pytest

from test_reservation_quote_contract import NOW, ORIGINS, quote_data, selected


def configuration():
    return {
        "apiSource": "capability",
        "capability": "validate_reservation_quote",
        "argumentsTemplate": '{"quote":{{provider_quote}},"expected":{{selection}}}',
        "quotePolicy": {
            "allowedCheckoutOrigins": list(ORIGINS),
            "requireCheckoutLink": True,
            "providerSelectedDimensions": [],
            "fingerprintVariable": "quote_fingerprint",
            "privateUrlVariable": "private_checkout_url",
            "publicConfirmationVariables": ["quote_room", "quote_total", "quote_currency"],
        },
        "responseMapping": {
            "quote_room": "$.public.room_id",
            "quote_total": "$.public.pricing.total",
            "quote_currency": "$.public.pricing.currency",
            "quote_fingerprint": "$.fingerprint",
            "private_checkout_url": "$.private.checkout_url",
        },
        "responseProjection": {"fields": [
            {"variable": "quote_room"},
            {"variable": "quote_total"},
            {"variable": "quote_currency"},
        ]},
    }


def caller_facts():
    return {
        "provider_quote": quote_data(),
        "selection": selected(),
        "caller_phone": "+14155550101",
    }


def confirmed_delivery():
    from botelier.voice.flows.native_execution import NativeConfirmation
    from botelier.voice.flows.native_quote_actions import prepare_quote

    config, facts = configuration(), caller_facts()
    prepared = prepare_quote(config, facts, now=NOW)
    facts.update(prepared.result.variables)
    fields = (
        *prepared.policy.public_confirmation_variables,
        prepared.policy.fingerprint_variable, "caller_phone",
    )
    confirmation = NativeConfirmation(
        "confirm", 7, {key: facts[key] for key in fields}, fields,
    )
    arguments = {
        "recipient": facts["caller_phone"],
        "body": "Review your selected reservation:\n" + facts["private_checkout_url"],
    }
    return config, facts, confirmation, arguments


def test_maps_exact_public_values_and_keeps_private_data_out_of_the_model_result():
    from botelier.voice.flows.native_quote_actions import prepare_quote

    facts = caller_facts()
    original = deepcopy(facts)
    prepared = prepare_quote(configuration(), facts, now=NOW)
    assert facts == original
    assert prepared.result.success
    assert prepared.result.variables["quote_total"] == "230.00"
    assert prepared.result.variables["private_checkout_url"] == quote_data()["checkout_url"]
    assert prepared.result.variables["quote_fingerprint"] == prepared.validated.fingerprint
    assert prepared.result.llm_data == {
        "quote_room": "suite", "quote_total": "230.00", "quote_currency": "USD",
    }
    assert "synthetic-test-only" not in json.dumps(prepared.result.llm_data)
    assert prepared.validated.fingerprint not in json.dumps(prepared.result.llm_data)
    assert "synthetic-test-only" not in repr(prepared)
    detached = prepared.result.variables
    detached["quote_total"] = "1"
    assert prepared.result.variables["quote_total"] == "230.00"


@pytest.mark.parametrize("update", [
    {"allowedCheckoutOrigins": ["{{caller_origin}}"]},
    {"allowedCheckoutOrigins": ["http://booking.example.invalid"]},
    {"allowedCheckoutOrigins": ["https://127.0.0.1"]},
    {"allowedCheckoutOrigins": list(ORIGINS) * 2},
    {"requireCheckoutLink": 1},
    {"providerSelectedDimensions": ["hotel_id"]},
    {"fingerprintVariable": "private_checkout_url"},
    {"publicConfirmationVariables": ["private_checkout_url"]},
    {"publicConfirmationVariables": ["quote_fingerprint"]},
    {"unknownAuthority": True},
])
def test_literal_policy_rejects_runtime_injection_ambiguous_scope_and_unknown_keys(update):
    from botelier.voice.flows.native_quote_actions import NativeQuoteError, prepare_quote

    config = configuration()
    config["quotePolicy"].update(update)
    with pytest.raises(NativeQuoteError, match="quote_policy"):
        prepare_quote(config, caller_facts(), now=NOW)


@pytest.mark.parametrize("variable,path", [
    ("private_checkout_url", "$.private.checkout_url"),
    ("aliased_private", "$.private.checkout_url"),
    ("aliased_fingerprint", "$.fingerprint"),
    ("whole_response", "$"),
])
def test_model_projection_cannot_reexpose_private_data_through_an_alias(variable, path):
    from botelier.voice.flows.native_quote_actions import NativeQuoteError, prepare_quote

    config = configuration()
    config["responseMapping"][variable] = path
    config["responseProjection"]["fields"].append({"variable": variable})
    with pytest.raises(NativeQuoteError, match="quote_projection"):
        prepare_quote(config, caller_facts(), now=NOW)


def test_requires_explicit_projection_and_rejects_caller_policy_in_arguments():
    from botelier.voice.flows.native_quote_actions import NativeQuoteError, prepare_quote

    config = configuration()
    del config["responseProjection"]
    with pytest.raises(NativeQuoteError, match="quote_projection"):
        prepare_quote(config, caller_facts(), now=NOW)
    config = configuration()
    config["argumentsTemplate"] = (
        '{"quote":{{provider_quote}},"expected":{{selection}},'
        '"allowedCheckoutOrigins":["https://attacker.example.invalid"]}'
    )
    with pytest.raises(NativeQuoteError, match="quote_arguments"):
        prepare_quote(config, caller_facts(), now=NOW)


def test_cleanup_cannot_disguise_a_private_url_before_the_privacy_check():
    from botelier.voice.flows.native_quote_actions import NativeQuoteError, prepare_quote

    config, facts = configuration(), caller_facts()
    facts["provider_quote"]["checkout_url"] += "&copy=synthetic-only"
    config["responseMapping"]["private_alias"] = "$.private.checkout_url"
    config["responseProjection"]["fields"].append({
        "variable": "private_alias", "cleanup": ["clean_text"],
    })
    with pytest.raises(NativeQuoteError, match="quote_projection"):
        prepare_quote(config, facts, now=NOW)


def test_prepares_only_the_validated_private_url_exception_not_a_second_consent_mechanism():
    from botelier.voice.flows.native_quote_actions import prepare_quote_delivery

    config, facts, confirmation, arguments = confirmed_delivery()
    assert "private_checkout_url" not in confirmation.values()
    assert "provider_quote" not in confirmation.values()
    prepared = prepare_quote_delivery(
        config, facts, confirmation, arguments,
        recipient_variable="caller_phone", now=NOW,
    )
    assert prepared.exempt_references == frozenset({"private_checkout_url"})
    assert {"caller_phone", "quote_fingerprint"} <= prepared.required_references
    assert prepared.validated.fingerprint == facts["quote_fingerprint"]


@pytest.mark.parametrize("change", [
    "missing_confirmation", "stale_price", "stale_recipient", "private_url",
    "expired", "second_url", "url_suffix", "url_in_subject", "unknown_argument",
])
def test_send_preparation_rejects_stale_or_changed_quote_recipient_and_url(change):
    from botelier.voice.flows.native_quote_actions import (
        NativeQuoteError, prepare_quote_delivery,
    )

    config, facts, confirmation, arguments = confirmed_delivery()
    now = NOW
    if change == "missing_confirmation":
        confirmation = None
    elif change == "stale_price":
        facts["provider_quote"]["pricing"].update(subtotal="201.00", total="231.00")
    elif change == "stale_recipient":
        facts["caller_phone"] = arguments["recipient"] = "+14155550102"
    elif change == "private_url":
        facts["private_checkout_url"] = arguments["body"] = "https://attacker.example.invalid"
    elif change == "expired":
        now += timedelta(minutes=11)
    elif change == "second_url":
        arguments["body"] += "\nhttps://attacker.example.invalid"
    elif change == "url_suffix":
        arguments["body"] += "unapproved-suffix"
    elif change == "url_in_subject":
        arguments["subject"] = facts["private_checkout_url"]
    else:
        arguments["authorization"] = "synthetic-sensitive-only"
    with pytest.raises(NativeQuoteError) as error:
        prepare_quote_delivery(
            config, facts, confirmation, arguments,
            recipient_variable="caller_phone", now=now,
        )
    assert "synthetic-sensitive-only" not in str(error.value)
    assert "synthetic-test-only" not in str(error.value)
    assert "attacker.example" not in str(error.value)


def test_a_fresh_url_for_the_same_confirmed_quote_still_requires_exact_body_binding():
    from botelier.voice.flows.native_quote_actions import prepare_quote_delivery

    config, facts, confirmation, arguments = confirmed_delivery()
    new_url = "https://booking.example.invalid/review/quote-suite-2?session=renewed-synthetic"
    facts["provider_quote"]["checkout_url"] = facts["private_checkout_url"] = new_url
    arguments["body"] = "Review your selected reservation:\n" + new_url
    prepared = prepare_quote_delivery(
        config, facts, confirmation, arguments,
        recipient_variable="caller_phone", now=NOW,
    )
    assert prepared.validated.fingerprint == facts["quote_fingerprint"]

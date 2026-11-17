"""Pure admission/privacy checks for linked native quote and delivery nodes."""

from copy import deepcopy
from urllib.parse import quote as encode_url

import pytest

from test_native_quote_actions import public_fields
from test_native_quote_bridge import quote_definition


def delivery_definition():
    source = quote_definition()
    source["nodes"][2:2] = [
        {"id": "confirm", "type": "confirmation", "data": {
            "confirmation": {
                "summaryTemplate": (
                    "Room {{quote_room}}; stay total {{quote_total}} "
                    "{{quote_currency}}, taxes {{quote_taxes}}, fees "
                    "{{quote_fees}}. Send the review link to {{caller_phone}}?"
                ),
                "confirmPrompt": "May I send it?",
                "variablesToConfirm": [
                    *public_fields().values(), "quote_fingerprint", "caller_phone",
                ],
                "allowEdit": False,
            },
        }},
        {"id": "send", "type": "api_request", "data": {"api": {
            "apiSource": "tool",
            "toolId": "00000000-0000-0000-0000-000000000007",
            "argumentsTemplate": (
                '{"recipient":{{caller_phone}},'
                '"body":"Review your selected reservation: {{private_checkout_url}}"}'
            ),
            "quoteDelivery": {
                "quoteNodeId": "quote", "recipientVariable": "caller_phone",
            },
        }}},
    ]
    source["edges"] = [
        {"id": "start-quote", "source": "start", "target": "quote"},
        {"id": "quote-confirm", "source": "quote", "target": "confirm",
         "sourceHandle": "success"},
        {"id": "confirm-send", "source": "confirm", "target": "send",
         "sourceHandle": "confirmed"},
        {"id": "send-done", "source": "send", "target": "done",
         "sourceHandle": "success"},
    ]
    return source


def test_admits_one_immutable_quote_confirmation_delivery_contract():
    from botelier.voice.flows.native_graph import compile_flow
    from test_native_graph import identity

    source = delivery_definition()
    compiled = compile_flow(source, identity())
    assert compiled.node("send").data()["api"]["quoteDelivery"] == {
        "quoteNodeId": "quote", "recipientVariable": "caller_phone",
    }


@pytest.mark.parametrize("change", [
    "missing_quote", "wrong_quote", "unknown_recipient", "private_recipient",
    "missing_total_consent", "missing_fingerprint_consent", "consent_bypass",
    "quote_bypass", "consent_before_quote", "unknown_policy_field",
])
def test_rejects_unbound_or_bypassable_quote_delivery(change):
    from botelier.voice.flows.native_graph import NativeGraphError, compile_flow
    from test_native_graph import identity

    source = delivery_definition()
    send = source["nodes"][3]["data"]["api"]["quoteDelivery"]
    confirmation = source["nodes"][2]["data"]["confirmation"]
    if change == "missing_quote":
        send["quoteNodeId"] = "not-here"
    elif change == "wrong_quote":
        send["quoteNodeId"] = "start"
    elif change == "unknown_recipient":
        send["recipientVariable"] = "not_here"
    elif change == "private_recipient":
        send["recipientVariable"] = "private_checkout_url"
    elif change == "missing_total_consent":
        confirmation["variablesToConfirm"].remove("quote_total")
    elif change == "missing_fingerprint_consent":
        confirmation["variablesToConfirm"].remove("quote_fingerprint")
    elif change == "consent_bypass":
        source["edges"].append({
            "id": "skip-confirm", "source": "quote", "target": "send",
            "sourceHandle": "error",
        })
    elif change == "quote_bypass":
        source["nodes"].insert(1, {"id": "branch", "type": "condition", "data": {
            "condition": {
                "variable": "caller_phone", "operator": "is_not_empty", "value": "",
            },
        }})
        source["edges"][0]["target"] = "branch"
        source["edges"].extend([
            {"id": "branch-quote", "source": "branch", "target": "quote",
             "sourceHandle": "true"},
            {"id": "skip-quote", "source": "branch", "target": "confirm",
             "sourceHandle": "false"},
        ])
    elif change == "consent_before_quote":
        source["edges"][0]["target"] = "confirm"
        source["edges"][1].update(source="confirm", target="quote", sourceHandle="confirmed")
        source["edges"][2].update(source="quote", target="send", sourceHandle="success")
    else:
        send["runtimeOverride"] = True
    with pytest.raises(NativeGraphError, match="quote_delivery"):
        compile_flow(source, identity())


def speech_definition(surface, text):
    source = quote_definition()
    source["variables"].extend([
        {"key": key, "type": "text"} for key in (
            "quote_fingerprint", "private_checkout_url", "caller_note", "items",
        )
    ])
    if surface == "global":
        source["globalPrompt"] = text
        return source
    if surface == "initial":
        source["nodes"][0]["data"]["greeting"] = text
        return source
    if surface == "instructions":
        source["nodes"][2]["data"]["instructions"] = text
        return source
    if surface == "end":
        source["nodes"][2]["data"]["closingMessage"] = text
        return source
    if surface == "transfer":
        source["nodes"][2].update(type="transfer", data={"transfer": {
            "phoneNumber": "+14155550120", "preTransferMessage": text,
        }})
        return source
    kind, data, handles = "message", {"message": text}, [None]
    if surface == "slot":
        kind, data = "collect_slot", {"slot": {
            "variableKey": "caller_note", "type": "text", "prompt": text,
        }}
    elif surface in {"form_prompt", "form_intro"}:
        kind, data = "collect_form", {
            "introMessage": text if surface == "form_intro" else "Details",
            "slots": [{
                "id": "note", "order": 0, "variableKey": "caller_note",
                "type": "text", "prompt": text if surface == "form_prompt" else "Note?",
            }],
        }
    elif surface.startswith("api_") and surface != "api_response":
        fields = {
            "api_thinking": "thinkingMessage", "api_success": "onSuccess",
            "api_instructions": "responseInstructions",
        }
        kind, data, handles = "api_request", {"api": {
            "apiSource": "custom", "url": "https://example.invalid/lookup",
            fields[surface]: text,
        }}, ["success"]
    elif surface == "api_response":
        kind, data, handles = "api_response", {"responsePresentation": {
            "arrayVariable": "items", "itemTemplate": text, "noResultsText": "None",
        }}, ["has_results", "no_results"]
    elif surface == "picker":
        kind, data, handles = "option_picker", {"optionPicker": {
            "sourceVariable": "items", "labelPath": "name", "prompt": text,
            "writes": [{"variableKey": "caller_note", "path": "name"}],
        }}, ["selected"]
    elif surface.startswith("confirmation_"):
        kind, data, handles = "confirmation", {"confirmation": {
            "summaryTemplate": text if surface == "confirmation_summary" else "Recipient",
            "confirmPrompt": text if surface == "confirmation_prompt" else "Proceed?",
            "variablesToConfirm": ["caller_phone"], "allowEdit": False,
        }}, ["confirmed"]
    source["nodes"].insert(2, {"id": "speech", "type": kind, "data": data})
    source["edges"][1]["target"] = "speech"
    source["edges"].extend(
        {"id": f"speech-end-{index}", "source": "speech", "target": "done",
         **({"sourceHandle": handle} if handle else {})}
        for index, handle in enumerate(handles)
    )
    return source


@pytest.mark.parametrize("surface", [
    "global", "initial", "instructions", "end", "transfer", "message",
    "slot", "form_prompt", "form_intro", "confirmation_summary",
    "confirmation_prompt", "api_thinking", "api_success",
    "api_instructions", "api_response", "picker",
])
@pytest.mark.parametrize("variable", [
    "private_checkout_url", "quote_fingerprint", "provider_quote",
])
def test_server_rejects_private_quote_references_on_every_speech_surface(surface, variable):
    from botelier.voice.flows.native_graph import NativeGraphError, compile_flow
    from test_native_graph import identity

    compile_flow(speech_definition(surface, "Safe configured speech"), identity())
    with pytest.raises(NativeGraphError, match="quote_private"):
        compile_flow(speech_definition(surface, "Speak {{" + variable + "}}"), identity())


def test_raw_quote_producer_must_explicitly_hide_its_unvalidated_model_projection():
    from botelier.voice.flows.native_graph import NativeGraphError, compile_flow
    from test_native_graph import identity

    source = quote_definition()
    producer = {"id": "fetch", "type": "api_request", "data": {"api": {
        "apiSource": "custom", "url": "https://example.invalid/quote",
        "responseMapping": {"provider_quote": "$.quote"},
        "responseProjection": {"fields": []},
    }}}
    source["nodes"].insert(1, producer)
    source["edges"][0]["target"] = "fetch"
    source["edges"].append({
        "id": "fetch-quote", "source": "fetch", "target": "quote",
        "sourceHandle": "success",
    })
    compile_flow(source, identity())
    unsafe = deepcopy(source)
    unsafe["nodes"][1]["data"]["api"].pop("responseProjection")
    with pytest.raises(NativeGraphError, match="quote_private"):
        compile_flow(unsafe, identity())


@pytest.mark.parametrize("form", [
    "bare", "relative", "encoded", "double_encoded", "bare_uppercase_host",
])
def test_runtime_privacy_also_rejects_encoded_or_schemeless_checkout_aliases(form):
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.native_quote_actions import NativeQuoteError
    from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe
    from test_native_graph import identity
    from test_native_quote_actions import caller_facts

    facts = caller_facts()
    private = facts["provider_quote"]["checkout_url"]
    aliases = {
        "bare": private.removeprefix("https://"),
        "relative": private.removeprefix("https:"),
        "encoded": encode_url(private, safe=""),
        "double_encoded": encode_url(encode_url(private, safe=""), safe=""),
        "bare_uppercase_host": private.removeprefix("https://").replace("booking", "BOOKING"),
    }
    compiled = compile_flow(quote_definition(), identity())
    with pytest.raises(NativeQuoteError, match="quote_private"):
        assert_quote_payload_safe(compiled, facts, {"room_label": aliases[form]})


def test_runtime_privacy_allows_unrelated_public_urls_and_plain_booking_domain():
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe
    from test_native_graph import identity
    from test_native_quote_actions import caller_facts

    assert_quote_payload_safe(compile_flow(quote_definition(), identity()), caller_facts(), {
        "website": "https://public.example.invalid/hotel",
        "booking_domain": "booking.example.invalid", "amount": "230.00",
    })

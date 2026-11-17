"""Synthetic booking-link graph; no provider, account, or price fallback."""

import json
import uuid
from copy import deepcopy

from test_native_quote_actions import configuration
from test_native_quote_delivery import _add_tool_and_sender
from test_reservation_quote_contract import quote_data


ROOMS = [
    {"id": "queen", "name": "Compact Queen", "rate_id": "flexible",
     "currency": "USD", "price_total": "180.00"},
    {"id": "suite", "name": "Ocean Suite", "rate_id": "flexible",
     "currency": "USD", "price_total": "230.00"},
]
STAY = {
    "check_in": "2026-12-01", "check_out": "2026-12-03",
    "adults": 2, "children": 0,
}
RECIPIENTS = {"SEND_SMS": "+14155550101", "SEND_EMAIL": "guest@example.invalid"}


def _json_template(payload, *typed_variables):
    text = json.dumps(payload)
    for name in typed_variables:
        token = "{{" + name + "}}"
        text = text.replace(json.dumps(token), token)
    return text


def booking_definition(tool_id, record_type_id, delivery_type, *, mcp_id=None):
    quote = configuration()
    fields = quote["quotePolicy"]["publicConfirmationFields"]
    def public(path):
        return "{{" + fields[path] + "}}"

    recipient = "caller_email" if delivery_type == "SEND_EMAIL" else "caller_phone"
    quote["argumentsTemplate"] = _json_template({
        "quote": "{{provider_quote}}",
        "expected": {
            **{key: "{{" + key + "}}" for key in STAY},
            "room_id": "{{selected_room_id}}", "rate_id": "{{selected_rate_id}}",
            "currency": "{{selected_currency}}",
        },
    }, "provider_quote", "adults", "children")
    parameters = "&".join(key + "={{" + key + "}}" for key in STAY)
    availability = {
        "apiSource": "custom", "method": "GET",
        "url": "https://pms.example.invalid/availability?" + parameters,
        "timeout": 2, "retryCount": 0,
        "responseMapping": {"available_rooms": "$.rooms"},
        "responseProjection": {"fields": [{"variable": "available_rooms"}]},
    }
    if mcp_id:
        availability = {
            "apiSource": "mcp", "mcpConnectionId": str(mcp_id),
            "mcpToolName": "availability",
            "argumentsTemplate": _json_template(
                {key: "{{" + key + "}}" for key in STAY}, "adults", "children",
            ),
            "responseMapping": {"available_rooms": "$.structuredContent.rooms"},
            "responseProjection": {"fields": [{"variable": "available_rooms"}]},
        }
    quote_endpoint = {
        "apiSource": "custom", "method": "GET",
        "url": "https://pms.example.invalid/reservations/quote?" + parameters
        + "&room_id={{selected_room_id}}&rate_id={{selected_rate_id}}",
        "timeout": 2, "retryCount": 0,
        "responseMapping": {"provider_quote": "$.reservation", "quote_status": "$.status"},
        "responseProjection": {"fields": [{"variable": "quote_status"}]},
    }
    confirmed = [*fields.values(), "quote_fingerprint", "selected_room_name", recipient]
    body = (
        "Room: {{selected_room_name}}. "
        f"Check-in: {public('check_in')}. Check-out: {public('check_out')}. "
        f"Adults: {public('adults')}; children: {public('children')}. "
        f"Subtotal: {public('pricing.currency')} {public('pricing.subtotal')}. "
        f"Tax: {public('pricing.tax_total')}. Fees: {public('pricing.fees_total')}. "
        f"Total: {public('pricing.currency')} {public('pricing.total')}. "
        "Review your reservation quote: {{private_checkout_url}}"
    )
    delivery = {
        "apiSource": "tool", "toolId": tool_id,
        "argumentsTemplate": json.dumps({
            "recipient": "{{" + recipient + "}}", "body": body,
            **({"subject": "Your reservation quote"} if delivery_type == "SEND_EMAIL" else {}),
        }),
        "quoteDelivery": {"quoteNodeId": "validate_quote", "recipientVariable": recipient},
        "responseMapping": {"delivery_status": "$.status"},
        "responseProjection": {"fields": [{"variable": "delivery_status"}]},
    }
    slots = [
        {"id": key, "variableKey": key, "type": "date" if "check_" in key else "number",
         "order": index, "prompt": {
             "check_in": "What is your check-in date?",
             "check_out": "What is your check-out date?",
             "adults": "How many adults?", "children": "How many children?",
         }[key],
         **({"validation": {
             "min": 1 if key == "adults" else 0, "max": 10, "allowDecimal": False,
         }} if key in {"adults", "children"} else {}),
         **({"validation": {"afterDateVariable": "check_in"}} if key == "check_out" else {}),
        }
        for index, key in enumerate(STAY)
    ]
    variables = [
        {"key": key, "type": slot_type}
        for key, slot_type in (
            ("check_in", "date"), ("check_out", "date"), ("adults", "number"),
            ("children", "number"), ("available_rooms", "text"),
            ("selected_room_id", "text"), ("selected_room_name", "text"),
            ("selected_rate_id", "text"), ("selected_currency", "text"),
            ("provider_quote", "text"), ("quote_status", "text"),
            ("delivery_status", "text"),
            (recipient, "email" if delivery_type == "SEND_EMAIL" else "phone"),
        )
    ]
    nodes = [
        {"id": "start", "type": "initial", "data": {"greeting": "", "waitForResponse": False}},
        {"id": "stay", "type": "collect_form", "data": {"slots": slots}},
        {"id": "availability", "type": "api_request", "data": {"api": availability}},
        {"id": "present", "type": "api_response", "data": {"responsePresentation": {
            "arrayVariable": "available_rooms", "introText": "Available rooms.",
            "itemTemplate": "{{index}}. {{name}}, estimated total {{currency}} {{price_total}}.",
            "outroText": "", "noResultsText": "No rooms were available.",
        }}},
        {"id": "picker", "type": "option_picker", "data": {"optionPicker": {
            "sourceVariable": "available_rooms", "labelPath": "name",
            "prompt": "Which room would you like?", "maxRetries": 2,
            "writes": [
                {"variableKey": "selected_room_id", "path": "id"},
                {"variableKey": "selected_room_name", "path": "name"},
                {"variableKey": "selected_rate_id", "path": "rate_id"},
                {"variableKey": "selected_currency", "path": "currency"},
            ],
        }}},
        {"id": "fetch_quote", "type": "api_request", "data": {"api": quote_endpoint}},
        {"id": "validate_quote", "type": "capability", "data": {"api": quote}},
        {"id": "contact", "type": "collect_slot", "data": {"slot": {
            "variableKey": recipient, "type": "email" if delivery_type == "SEND_EMAIL" else "phone",
            "prompt": "Where should I send your reservation review link?",
        }}},
        {"id": "confirm", "type": "confirmation", "data": {"confirmation": {
            "summaryTemplate": (
                f"You chose {{{{selected_room_name}}}}, {public('check_in')} to {public('check_out')}, "
                f"{public('adults')} adults and {public('children')} children. "
                f"Subtotal {public('pricing.currency')} {public('pricing.subtotal')}, "
                f"tax {public('pricing.tax_total')}, fees {public('pricing.fees_total')}, "
                f"total {public('pricing.currency')} {public('pricing.total')}. "
                f"Price basis: {public('pricing.basis')}."
            ),
            "confirmPrompt": "May I send this review link to {{" + recipient + "}}?",
            "variablesToConfirm": confirmed, "deliveryMode": "static", "allowEdit": False,
        }}},
        {"id": "delivery", "type": "api_request", "data": {"api": delivery}},
        {"id": "save", "type": "save_record", "data": {"saveRecord": {
            "recordTypeId": str(record_type_id), "status": "link_accepted",
            "mapping": {
                **{path.replace(".", "_"): "{{" + variable + "}}" for path, variable in fields.items()},
                "room_name": "{{selected_room_name}}", "recipient": "{{" + recipient + "}}",
            },
        }}},
        {"id": "done", "type": "end", "data": {
            "closingMessage": "Your reservation review link was accepted for sending. Thank you.",
        }},
    ]
    handles = {
        "availability": "success", "present": "has_results",
        "picker": "selected", "fetch_quote": "success",
        "validate_quote": "success", "confirm": "confirmed", "delivery": "success",
    }
    edges = [
        {"id": first["id"] + "-" + second["id"], "source": first["id"], "target": second["id"],
         **({"sourceHandle": handles[first["id"]]} if first["id"] in handles else {})}
        for first, second in zip(nodes, nodes[1:])
    ]
    nodes.append({"id": "unavailable", "type": "end", "data": {"closingMessage": ""}})
    edges.append({
        "id": "present-unavailable", "source": "present", "target": "unavailable",
        "sourceHandle": "no_results",
    })
    return {"initial_node": "start", "variables": variables, "nodes": nodes, "edges": edges}


def seed_booking(fixture, delivery_type, *, mcp=False):
    from botelier.models.flow_version import FlowVersion
    from test_native_actions import _native_mcp_policy

    tool_id = "offline-complete-" + delivery_type.lower()
    _add_tool_and_sender(fixture, tool_id, delivery_type)
    fields = configuration()["quotePolicy"]["publicConfirmationFields"]
    db = fixture.factory()
    try:
        record_type_id = uuid.uuid4()
        db.add(fixture.effect_models["RecordType"](
            id=record_type_id, account_id=uuid.UUID(fixture.account_id),
            name="Reservation quotes sent", slug="reservation-quotes-sent",
            fields=[
                {"key": path.replace(".", "_"), "type": (
                    "number" if path in {"adults", "children"} else "text"
                ), "required": True}
                for path in fields
            ] + [
                {"key": "room_name", "type": "text", "required": True},
                {"key": "recipient", "type": "text", "required": True},
            ],
            status_options=[{"value": "link_accepted", "label": "Link accepted for sending"}],
            is_active=True,
        ))
        db.add(fixture.effect_models["CallLog"](
            id=uuid.uuid4(), account_id=uuid.UUID(fixture.account_id),
            call_sid=fixture.identity.call_sid, assistant_id=uuid.UUID(fixture.assistant_id),
            status="completed", outcome="completed",
        ))
        mcp_id = None
        if mcp:
            from botelier.models.mcp_connection import MCPAuthType, MCPConnection, MCPTransportType

            mcp_id = uuid.uuid4()
            db.add(MCPConnection(
                id=mcp_id, account_id=uuid.UUID(fixture.account_id), name="Synthetic room inventory",
                server_url="https://mcp.example.invalid/mcp", auth_type=MCPAuthType.NONE,
                transport_type=MCPTransportType.STREAMABLE_HTTP, is_active=True,
                discovered_tools=[{"name": "availability", "parameters": {
                    "type": "object", "properties": {
                        key: {"type": "string" if "check_" in key else "integer"} for key in STAY
                    }, "required": list(STAY),
                }}],
                connection_config=_native_mcp_policy(
                    db, fixture, mcp_id, enabled=["availability"], read_only=["availability"],
                ),
            ))
        source = booking_definition(tool_id, record_type_id, delivery_type, mcp_id=mcp_id)
        version = db.query(FlowVersion).filter(
            FlowVersion.id == uuid.UUID(fixture.identity.flow_version_id),
        ).one()
        version.flow_config = deepcopy(source)
        db.commit()
        return source
    finally:
        db.close()


def authoritative_quote():
    data = quote_data()
    data["checkout_url"] += "&copy=1"
    return deepcopy(data)

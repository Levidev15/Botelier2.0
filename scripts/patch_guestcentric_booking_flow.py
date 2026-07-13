"""
Full-replacement patch for the GuestCentric CRS booking flow.

Constructs the corrected config from the canonical template spec (mirroring
store.ts) and replaces tools.config entirely rather than patching in place.
Runtime-specific values (integrationId, account positions) are read from the
existing DB row and re-applied so no operator work is lost.

Creates a new flow_versions row with status=DRAFT so an operator can review
and publish via the editor.

Usage
─────
    python scripts/patch_guestcentric_booking_flow.py [--dry-run]

Environment
───────────
    DATABASE_URL  — PostgreSQL connection string (required)
"""

from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "botelier", "backend"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TOOL_ID = "01ae4110-2916-477b-97d3-5f98e86dd471"


def _read_integration_id(nodes: list[dict]) -> str:
    """Return the live integrationId already set on the API nodes (if any)."""
    for n in nodes:
        iid = n.get("data", {}).get("api", {}).get("integrationId", "")
        if iid:
            return iid
    return ""


def build_corrected_config(existing_config: dict) -> dict:
    """
    Construct the complete, corrected flow config from the canonical template
    spec.  Re-applies the integrationId from the existing row so the live
    integration link is preserved.
    """
    integration_id = _read_integration_id(existing_config.get("nodes", []))

    # ── variables ─────────────────────────────────────────────────────────────
    variables = [
        {"key": "checkin",                "type": "date",   "description": "Check-in date (YYYY-MM-DD)",           "required": True},
        {"key": "checkout",               "type": "date",   "description": "Check-out date (YYYY-MM-DD)",                                               "required": True},
        {"key": "adults",                 "type": "number", "description": "Number of adult guests",                                                     "required": True},
        {"key": "number_of_adults",       "type": "number", "description": "Adults for booking body (auto-copied from adults)",                          "required": False, "defaultValue": "1"},
        {"key": "available_rooms",        "type": "text",   "description": "Available room names from GuestCentric",                                     "required": False},
        {"key": "rates",                  "type": "text",   "description": "Available rate plan display names from GuestCentric",                        "required": False},
        {"key": "room_rates",             "type": "text",   "description": "Full room+rate combinations JSON from GuestCentric",                         "required": False},
        {"key": "room_type_code",         "type": "text",   "description": "Selected room type code",                                                    "required": True},
        {"key": "rate_plan_code",         "type": "text",   "description": "Selected rate plan code",                                                    "required": True},
        {"key": "room_rate_code",         "type": "text",   "description": "Room+rate combination code (auto-derived)",                                  "required": True},
        {"key": "total_price",            "type": "number", "description": "Total stay price (auto-derived)",                                            "required": True},
        {"key": "number_of_rooms",        "type": "number", "description": "Number of rooms to book",                                                    "required": False, "defaultValue": "1"},
        {"key": "number_of_children",     "type": "number", "description": "Number of children",                                                         "required": False, "defaultValue": "0"},
        {"key": "guest_first_name",       "type": "text",   "description": "Guest first name",                                                           "required": True},
        {"key": "guest_last_name",        "type": "text",   "description": "Guest last name",                                                            "required": True},
        {"key": "guest_email",            "type": "text",   "description": "Guest email",                                                                "required": True},
        {"key": "guest_phone",            "type": "text",   "description": "Guest phone",                                                                "required": True},
        {"key": "guest_address",          "type": "text",   "description": "Guest mailing address",                                                      "required": True},
        {"key": "guest_city",             "type": "text",   "description": "Guest city",                                                                 "required": True},
        {"key": "guest_postal_code",      "type": "text",   "description": "Guest postal code",                                                          "required": True},
        {"key": "guest_country",          "type": "text",   "description": "Guest country",                                                              "required": True},
        {"key": "hotels",                 "type": "text",   "description": "JSON array of hotel IDs for cancellation policy lookup",                     "required": False},
        {"key": "cancellation_policy_id", "type": "text",   "description": "Cancellation policy ID (auto-derived)",                                     "required": True},
        {"key": "meal_plan_id",           "type": "text",   "description": "Included meal plan ID (auto-derived)",                                       "required": True},
        {"key": "meal_plan_net",          "type": "number", "description": "Meal plan net price",                                                        "required": False, "defaultValue": "0"},
        {"key": "meal_plan_tax",          "type": "number", "description": "Meal plan tax",                                                              "required": False, "defaultValue": "0"},
        {"key": "meal_plan_total",        "type": "number", "description": "Meal plan total price",                                                      "required": False, "defaultValue": "0"},
        {"key": "crs_reservation_code",   "type": "text",   "description": "CRS reservation code from GuestCentric",                                    "required": False},
        {"key": "hotel_reservation_code", "type": "text",   "description": "Hotel-side reservation code from GuestCentric",                             "required": False},
        {"key": "booking_status",         "type": "text",   "description": "Reservation status from GuestCentric",                                      "required": False},
    ]

    def _api(endpoint_id: str, endpoint_name: str, method: str = "GET",
             thinking: str = "", response_mapping: dict | None = None,
             auto_mapping: dict | None = None, response_instructions: str = "",
             on_error: str = "", query_param_overrides: dict | None = None,
             timeout: int = 15, retry_count: int = 1) -> dict:
        node: dict = {
            "method": method,
            "url": "",
            "apiSource": "integration",
            "integrationId": integration_id,
            "integrationSlug": "guestcentric-crs",
            "endpointId": endpoint_id,
            "endpointName": endpoint_name,
            "thinkingMessage": thinking,
            "responseMapping": response_mapping or {},
            "autoMappingSource": auto_mapping or response_mapping or {},
            "responseInstructions": response_instructions,
            "timeout": timeout,
            "retryCount": retry_count,
        }
        if on_error:
            node["onError"] = on_error
        if query_param_overrides:
            node["queryParamOverrides"] = query_param_overrides
        return node

    # ── nodes ──────────────────────────────────────────────────────────────────
    # Preserve any custom positions from the existing config
    pos: dict[str, dict] = {}
    for n in existing_config.get("nodes", []):
        pos[n["id"]] = n.get("position", {})

    def _p(node_id: str, default_x: int, default_y: int) -> dict:
        return pos.get(node_id, {"x": default_x, "y": default_y})

    nodes = [
        # ── initial node ──────────────────────────────────────────────────────
        {
            "id": "start_1",
            "type": "initial",
            "position": _p("start_1", 795, -75),
            "data": {
                "name": "Greeting",
                "systemPrompt": (
                    "You are a reservations agent for a property using the GuestCentric CRS. "
                    "Help callers check room availability and complete a booking. "
                    "Collect check-in and check-out dates and guest count first, then check live "
                    "availability via the integration. Present the available room types and rate "
                    "plans clearly, ask the caller to choose one of each, then collect their name, "
                    "email, and phone. Always confirm the full booking summary before submitting "
                    "to GuestCentric."
                ),
                "greeting": (
                    "Thank you for calling. I'd be happy to help you check availability and book "
                    "a room. Could I start with your desired check-in and check-out dates?"
                ),
            },
        },
        # ── date / guest collection ───────────────────────────────────────────
        {
            "id": "collect_checkin",
            "type": "collect_slot",
            "position": _p("collect_checkin", 750, 180),
            "data": {
                "name": "Check-in Date",
                "slot": {
                    "variableKey": "checkin",
                    "prompt": "What date would you like to check in?",
                    "instructions": (
                        "Once the caller provides the date, store it in YYYY-MM-DD format "
                        "(e.g. 2025-12-15). The date must be today or a future date."
                    ),
                    "type": "date",
                    "validation": {"requireFuture": True},
                    "retryPrompt": "Please provide a future check-in date.",
                    "maxRetries": 3,
                    "useBuiltInValidator": True,
                },
            },
        },
        {
            "id": "collect_checkout",
            "type": "collect_slot",
            "position": _p("collect_checkout", 1125, 375),
            "data": {
                "name": "Check-out Date",
                "slot": {
                    "variableKey": "checkout",
                    "prompt": "And what date will you be checking out?",
                    "instructions": (
                        "Once the caller provides the date, store it in YYYY-MM-DD format "
                        "(e.g. 2025-12-18). The date must be after the check-in date."
                    ),
                    "type": "date",
                    "validation": {
                        "requireFuture": True,
                        "crossFieldCheck": {
                            "compareWith": "checkin",
                            "operator": "after",
                            "errorMessage": "Check-out must be after your check-in date.",
                        },
                    },
                    "retryPrompt": "Your check-out date must be after your check-in date. Could you repeat it?",
                    "maxRetries": 3,
                    "useBuiltInValidator": True,
                },
            },
        },
        # ── guest count — keeps the operator-created node ID ──────────────────
        {
            "id": "node_1783660424526_1",
            "type": "collect_slot",
            "position": _p("node_1783660424526_1", 750, 615),
            "data": {
                "name": "Guest Count",
                "slot": {
                    "variableKey": "adults",
                    "prompt": "How many adults will be staying?",
                    "type": "number",
                    "validation": {"min": 1, "max": 4},
                    "retryPrompt": "Please give me a number between 1 and 4.",
                    "maxRetries": 3,
                },
            },
        },
        # ── sync adults → number_of_adults ────────────────────────────────────
        {
            "id": "sync_number_of_adults",
            "type": "set_variable",
            "position": _p("sync_number_of_adults", 750, 750),
            "data": {
                "name": "Sync Adults for Booking",
                "setVariable": {
                    "variableKey": "number_of_adults",
                    "valueType": "template",
                    "value": "{{adults}}",
                },
            },
        },
        # ── availability check ────────────────────────────────────────────────
        {
            "id": "check_availability",
            "type": "api_request",
            "position": _p("check_availability", 795, 795),
            "data": {
                "name": "Check Availability (GuestCentric)",
                "instructions": (
                    "After this node completes, present the available room types clearly by "
                    "name, then present the available rate plans. Ask the caller to choose one "
                    "of each. If no rooms are available or this call fails, apologise and ask "
                    "if they would like to try different dates — do NOT transfer the call."
                ),
                "api": _api(
                    endpoint_id="hotel_rooms",
                    endpoint_name="Hotel Rooms & Rates",
                    thinking="Let me check room availability for those dates — one moment please.",
                    response_mapping={
                        "available_rooms": "$.rooms[*].name",
                        "rates":           "$.rates[*].rate_plan_name",
                        "room_rates":      "$.room_rates",
                    },
                    response_instructions=(
                        "List the available room types by name. Then list the available rate "
                        "plans. Ask which room type and rate plan they would like."
                    ),
                    on_error=(
                        "I wasn't able to retrieve available rooms right now. Would you like "
                        "to try different check-in or check-out dates?"
                    ),
                    query_param_overrides={
                        "rate_plan_code": "",
                        "room_type_code": "",
                    },
                ),
            },
        },
        # ── room + rate selection ─────────────────────────────────────────────
        {
            "id": "collect_room",
            "type": "collect_slot",
            "position": _p("collect_room", 750, 950),
            "data": {
                "name": "Room Type Selection",
                "instructions": (
                    "Present the available room types from {{available_rooms}} to the caller. "
                    "When the caller picks one, identify the matching room_type_code from the "
                    "availability data and store that exact code as room_type_code."
                ),
                "slot": {
                    "variableKey": "room_type_code",
                    "prompt": (
                        "Which room type would you prefer? The available options are: "
                        "{{available_rooms}}. I will record the exact room type code for "
                        "your selection."
                    ),
                    "type": "text",
                    "retryPrompt": "Could you repeat which room type you'd like?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_rate",
            "type": "collect_slot",
            "position": _p("collect_rate", 750, 1100),
            "data": {
                "name": "Rate Plan Selection",
                "instructions": (
                    "Present the available rate plans from {{rates}} to the caller. "
                    "When the caller picks one, identify the matching rate_plan_code from "
                    "the availability data and store that exact code as rate_plan_code. "
                    "If {{rates}} is empty or unavailable, use the rate plan codes from "
                    "{{room_rates}} instead."
                ),
                "slot": {
                    "variableKey": "rate_plan_code",
                    "prompt": (
                        "And which rate plan would you like? The available plans are: "
                        "{{rates}}. I will record the exact rate plan code for your selection."
                    ),
                    "type": "text",
                    "retryPrompt": "Could you repeat which rate plan you'd like?",
                    "maxRetries": 3,
                },
            },
        },
        # ── confirm room+rate (filtered re-check) ─────────────────────────────
        {
            "id": "confirm_room_rate",
            "type": "api_request",
            "position": _p("confirm_room_rate", 750, 1250),
            "data": {
                "name": "Confirm Room Rate (GuestCentric)",
                "instructions": (
                    "Re-checks availability filtered to the caller's selected room type and "
                    "rate plan codes to capture the exact room_rate_code, total_price, and "
                    "meal_plan_id needed to book. Do not narrate this step to the caller — "
                    "proceed silently."
                ),
                "api": _api(
                    endpoint_id="hotel_rooms",
                    endpoint_name="Hotel Rooms & Rates",
                    response_mapping={
                        "room_rate_code": "$.room_rates[0].room_rate_code",
                        "total_price":    "$.room_rates[0].total_price",
                        "meal_plan_id":   "$.room_rates[0].meal_plan_prices.included.id",
                    },
                    query_param_overrides={
                        "room_type_code": "{{room_type_code}}",
                        "rate_plan_code": "{{rate_plan_code}}",
                    },
                    response_instructions=(
                        "Do not mention this lookup to the caller. If no matching room rate "
                        "is returned, apologise and offer to pick a different room type or "
                        "rate plan."
                    ),
                    on_error=(
                        "I wasn't able to confirm that room and rate combination. Please "
                        "choose a different room type or rate plan."
                    ),
                ),
            },
        },
        # ── build hotels array ────────────────────────────────────────────────
        {
            "id": "build_hotels_array",
            "type": "set_variable",
            "position": _p("build_hotels_array", 750, 1400),
            "data": {
                "name": "Build Hotels Array",
                "setVariable": {
                    "variableKey": "hotels",
                    "valueType": "template",
                    "value": '["{{hotel_id}}"]',
                },
            },
        },
        # ── cancellation policy ───────────────────────────────────────────────
        {
            "id": "check_cancellation_policy",
            "type": "api_request",
            "position": _p("check_cancellation_policy", 750, 1550),
            "data": {
                "name": "Get Cancellation Policy (GuestCentric)",
                "instructions": (
                    "Looks up the property's cancellation policy ID required by the booking "
                    "endpoint. Do not narrate this step to the caller — proceed silently to "
                    "collecting their contact details."
                ),
                "api": _api(
                    endpoint_id="hotel_cancellation_policies",
                    endpoint_name="Cancellation Policies",
                    response_mapping={"cancellation_policy_id": "$[0].id"},
                    response_instructions="Do not mention this lookup to the caller.",
                    on_error=(
                        "I had a technical issue retrieving the cancellation policy. I will "
                        "proceed and note the policy should be confirmed."
                    ),
                ),
            },
        },
        # ── guest contact details ─────────────────────────────────────────────
        {
            "id": "collect_first_name",
            "type": "collect_slot",
            "position": _p("collect_first_name", 750, 1700),
            "data": {
                "name": "Guest First Name",
                "slot": {
                    "variableKey": "guest_first_name",
                    "prompt": "May I have the guest's first name for the reservation?",
                    "type": "text",
                    "retryPrompt": "Could you spell the first name for me?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_last_name",
            "type": "collect_slot",
            "position": _p("collect_last_name", 750, 1850),
            "data": {
                "name": "Guest Last Name",
                "slot": {
                    "variableKey": "guest_last_name",
                    "prompt": "And the last name?",
                    "type": "text",
                    "retryPrompt": "Could you spell the last name for me?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_email",
            "type": "collect_slot",
            "position": _p("collect_email", 750, 2000),
            "data": {
                "name": "Guest Email",
                "slot": {
                    "variableKey": "guest_email",
                    "prompt": "What's the best email address for the booking confirmation?",
                    "type": "text",
                    "retryPrompt": "Could you repeat the email address?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_phone",
            "type": "collect_slot",
            "position": _p("collect_phone", 750, 2150),
            "data": {
                "name": "Guest Phone",
                "slot": {
                    "variableKey": "guest_phone",
                    "prompt": "And a good contact phone number?",
                    "type": "text",
                    "retryPrompt": "Could you repeat the phone number?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_guest_address",
            "type": "collect_slot",
            "position": _p("collect_guest_address", 750, 2300),
            "data": {
                "name": "Guest Address",
                "slot": {
                    "variableKey": "guest_address",
                    "prompt": "Could I get your mailing address for the reservation?",
                    "type": "text",
                    "retryPrompt": "Could you repeat your street address?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_guest_city",
            "type": "collect_slot",
            "position": _p("collect_guest_city", 750, 2450),
            "data": {
                "name": "Guest City",
                "slot": {
                    "variableKey": "guest_city",
                    "prompt": "And which city?",
                    "type": "text",
                    "retryPrompt": "Could you repeat the city?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_guest_postal_code",
            "type": "collect_slot",
            "position": _p("collect_guest_postal_code", 750, 2600),
            "data": {
                "name": "Guest Postal Code",
                "slot": {
                    "variableKey": "guest_postal_code",
                    "prompt": "What's the postal or ZIP code?",
                    "type": "text",
                    "retryPrompt": "Could you repeat the postal code?",
                    "maxRetries": 3,
                },
            },
        },
        {
            "id": "collect_guest_country",
            "type": "collect_slot",
            "position": _p("collect_guest_country", 750, 2750),
            "data": {
                "name": "Guest Country",
                "slot": {
                    "variableKey": "guest_country",
                    "prompt": "And the country?",
                    "type": "text",
                    "retryPrompt": "Could you repeat the country?",
                    "maxRetries": 3,
                },
            },
        },
        # ── booking confirmation ──────────────────────────────────────────────
        {
            "id": "confirm_details",
            "type": "confirmation",
            "position": _p("confirm_details", 750, 2900),
            "data": {
                "name": "Confirm Booking Details",
                "confirmation": {
                    "prompt": "Let me confirm your booking details before I submit:",
                    "fields": [
                        {"label": "Check-in",          "variableKey": "checkin"},
                        {"label": "Check-out",         "variableKey": "checkout"},
                        {"label": "Adults",            "variableKey": "adults"},
                        {"label": "Room Type",         "variableKey": "room_type_code"},
                        {"label": "Rate Plan",         "variableKey": "rate_plan_code"},
                        {"label": "Total Price",       "variableKey": "total_price"},
                        {"label": "Guest Name",        "variableKey": "guest_first_name"},
                        {"label": "Last Name",         "variableKey": "guest_last_name"},
                        {"label": "Email",             "variableKey": "guest_email"},
                        {"label": "Phone",             "variableKey": "guest_phone"},
                    ],
                    "allowEdit": True,
                    "deliveryMode": "guided",
                },
            },
        },
        # ── booking submission ────────────────────────────────────────────────
        {
            "id": "create_booking",
            "type": "api_request",
            "position": _p("create_booking", 750, 3050),
            "data": {
                "name": "Book Reservation (GuestCentric)",
                "instructions": (
                    "Submits the reservation to GuestCentric. After this node completes, "
                    "read the confirmation code back to the caller clearly, spelling it out "
                    "if needed."
                ),
                "api": _api(
                    endpoint_id="book_reservation",
                    endpoint_name="Book Reservation",
                    method="POST",
                    thinking="Creating your reservation in GuestCentric now — just a moment.",
                    response_mapping={
                        "crs_reservation_code":   "$.reservations[0].crs_reservation_code",
                        "hotel_reservation_code": "$.reservations[0].hotel_reservation_code",
                        "booking_status":         "$.reservations[0].status",
                    },
                    response_instructions=(
                        "Tell the caller their reservation is confirmed and read out their "
                        "confirmation code: {{crs_reservation_code}}. Offer to repeat it."
                    ),
                    on_error=(
                        "I'm sorry, there was a problem submitting your reservation. Could "
                        "you confirm your details are correct and I will try once more?"
                    ),
                    timeout=20,
                ),
            },
        },
        # ── end ───────────────────────────────────────────────────────────────
        {
            "id": "end_success",
            "type": "end",
            "position": _p("end_success", 750, 3200),
            "data": {
                "name": "Booking Confirmed",
                "closingMessage": (
                    "Your reservation is confirmed! Your confirmation code is "
                    "{{crs_reservation_code}}. We look forward to welcoming you. "
                    "Is there anything else I can help you with?"
                ),
            },
        },
    ]

    # ── edges ──────────────────────────────────────────────────────────────────
    edges = [
        {"id": "e1",    "source": "start_1",                  "target": "collect_checkin"},
        {"id": "e2",    "source": "collect_checkin",           "target": "collect_checkout"},
        {"id": "e3",    "source": "collect_checkout",          "target": "node_1783660424526_1"},
        {"id": "e3b",   "source": "node_1783660424526_1",      "target": "sync_number_of_adults"},
        {"id": "e4",    "source": "sync_number_of_adults",     "target": "check_availability"},
        {"id": "e5",    "source": "check_availability",        "target": "collect_room"},
        {"id": "e6",    "source": "collect_room",              "target": "collect_rate"},
        {"id": "e6b",   "source": "collect_rate",              "target": "confirm_room_rate"},
        {"id": "e6c",   "source": "confirm_room_rate",         "target": "build_hotels_array"},
        {"id": "e6d",   "source": "build_hotels_array",        "target": "check_cancellation_policy"},
        {"id": "e7",    "source": "check_cancellation_policy", "target": "collect_first_name"},
        {"id": "e8",    "source": "collect_first_name",        "target": "collect_last_name"},
        {"id": "e9",    "source": "collect_last_name",         "target": "collect_email"},
        {"id": "e10",   "source": "collect_email",             "target": "collect_phone"},
        {"id": "e10b",  "source": "collect_phone",             "target": "collect_guest_address"},
        {"id": "e10c",  "source": "collect_guest_address",     "target": "collect_guest_city"},
        {"id": "e10d",  "source": "collect_guest_city",        "target": "collect_guest_postal_code"},
        {"id": "e10e",  "source": "collect_guest_postal_code", "target": "collect_guest_country"},
        {"id": "e11",   "source": "collect_guest_country",     "target": "confirm_details"},
        {"id": "e12",   "source": "confirm_details",           "target": "create_booking"},
        {"id": "e13",   "source": "create_booking",            "target": "end_success"},
    ]

    return {
        "variables":    variables,
        "nodes":        nodes,
        "edges":        edges,
        "globalPrompt": "",
        "initial_node": "start_1",
    }


def apply(dry_run: bool = False) -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    engine = create_engine(db_url)
    db = sessionmaker(bind=engine)()

    try:
        row = db.execute(
            text("SELECT config FROM tools WHERE id = :id"), {"id": TOOL_ID}
        ).fetchone()
        if not row:
            raise RuntimeError(f"Tool {TOOL_ID} not found")

        existing = row[0] if isinstance(row[0], dict) else json.loads(row[0])

        # Full replacement from corrected template spec
        new_config = build_corrected_config(existing)
        config_json = json.dumps(new_config)

        print(f"Built corrected config: {len(new_config['nodes'])} nodes, "
              f"{len(new_config['edges'])} edges")

        # Verify critical mappings
        ca = next(n for n in new_config["nodes"] if n["id"] == "check_availability")
        print(f"  rates mapping:  {ca['data']['api']['responseMapping']['rates']}")
        print(f"  room_rates:     {ca['data']['api']['responseMapping']['room_rates']}")

        crm = next(n for n in new_config["nodes"] if n["id"] == "confirm_room_rate")
        print(f"  crm overrides:  {crm['data']['api'].get('queryParamOverrides')}")

        cr = next(n for n in new_config["nodes"] if n["id"] == "collect_rate")
        print(f"  collect_rate instructions present: {'instructions' in cr['data']}")

        if dry_run:
            print("\n[DRY RUN] No changes written.")
            return

        # Replace tools.config entirely
        db.execute(
            text("UPDATE tools SET config = CAST(:cfg AS json), updated_at = NOW() "
                 "WHERE id = :id"),
            {"cfg": config_json, "id": TOOL_ID},
        )

        # Create a DRAFT flow_versions row for review before publishing
        latest = db.execute(
            text("SELECT version_number FROM flow_versions WHERE tool_id = :tid "
                 "ORDER BY version_number DESC LIMIT 1"),
            {"tid": TOOL_ID},
        ).fetchone()
        next_v = (latest[0] + 1) if latest else 1

        db.execute(
            text("""
                INSERT INTO flow_versions
                    (id, tool_id, version_number, status, flow_config, created_at)
                VALUES (:id, :tid, :vnum, 'DRAFT', CAST(:cfg AS jsonb), NOW())
            """),
            {"id": str(uuid.uuid4()), "tid": TOOL_ID, "vnum": next_v, "cfg": config_json},
        )
        db.commit()
        print(f"\n✅ tools.config replaced (full), flow_versions v{next_v} DRAFT created.")

    except Exception as exc:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    apply(dry_run=dry)

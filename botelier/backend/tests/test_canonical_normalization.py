"""Canonical PMS normalization tests (Task #328).

These call each vendor adapter's ``normalize()`` directly with recorded raw
responses (``tests/fixtures/pms/<vendor>/<endpoint>.json``). No DB, no HTTP —
normalizers are pure functions of the raw JSON body.

The headline guarantee: for the SAME booking scenario, Opera Cloud and
GuestCentric normalize into a byte-identical canonical dict, so a consumer of the
canonical envelope cannot tell which vendor produced the data.
"""

import json
from pathlib import Path

from botelier.services.integration_runtime.adapters import (
    GUESTCENTRIC_ADAPTER,
    OPERA_ADAPTER,
)
from botelier.services.integration_runtime.canonical import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalEntity,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "pms"


def _load(vendor: str, name: str) -> dict:
    with open(_FIXTURES / vendor / f"{name}.json") as fh:
        return json.load(fh)


# --- Expected canonical items for the shared scenario -----------------------
# Same booking: Jane Doe, DLX/BAR, 2026-08-01 -> 2026-08-03, 450.00 USD, 2 adults.
EXPECTED_RESERVATION = {
    "reservation_id": "R-12345",
    "confirmation_number": "CONF987",
    "status": "confirmed",
    "guest_first_name": "Jane",
    "guest_last_name": "Doe",
    "arrival_date": "2026-08-01",
    "departure_date": "2026-08-03",
    "room_type_code": "DLX",
    "rate_plan_code": "BAR",
    "adults": 2,
    "children": 0,
    "total_amount": 450.0,
    "currency": "USD",
}

EXPECTED_AVAILABILITY = {
    "room_type_code": "DLX",
    "room_name": "Deluxe Room",
    "rate_plan_code": "BAR",
    "arrival_date": "2026-08-01",
    "departure_date": "2026-08-03",
    "available": True,
    "total_amount": 450.0,
    "currency": "USD",
}


# --- Cross-vendor parity (the core deliverable) -----------------------------
def test_reservation_parity_across_vendors():
    opera = OPERA_ADAPTER.normalize(
        CanonicalEntity.RESERVATION.value, "get_reservation", _load("opera", "get_reservation")
    )
    gc = GUESTCENTRIC_ADAPTER.normalize(
        CanonicalEntity.RESERVATION.value, "view_reservation", _load("guestcentric", "view_reservation")
    )

    assert opera == gc, "Opera and GuestCentric reservations must be indistinguishable"
    assert opera["schema_version"] == CANONICAL_SCHEMA_VERSION
    assert opera["entity"] == "reservation"
    assert opera["items"] == [EXPECTED_RESERVATION]


def test_availability_parity_across_vendors():
    opera = OPERA_ADAPTER.normalize(
        CanonicalEntity.AVAILABILITY.value, "check_availability", _load("opera", "check_availability")
    )
    gc = GUESTCENTRIC_ADAPTER.normalize(
        CanonicalEntity.AVAILABILITY.value, "hotel_rooms", _load("guestcentric", "hotel_rooms")
    )

    assert opera == gc, "Opera and GuestCentric availability must be indistinguishable"
    assert opera["entity"] == "availability"
    assert opera["items"] == [EXPECTED_AVAILABILITY]


# --- Envelope contract ------------------------------------------------------
def test_envelope_shape():
    env = OPERA_ADAPTER.normalize(
        CanonicalEntity.RESERVATION.value, "get_reservation", _load("opera", "get_reservation")
    )
    assert set(env.keys()) == {"schema_version", "entity", "items"}
    assert isinstance(env["items"], list)
    # Every canonical reservation item exposes the full field set (stable shape).
    assert set(env["items"][0].keys()) == set(EXPECTED_RESERVATION.keys())


# --- Single-vendor entity coverage (Opera) ----------------------------------
def test_opera_guest_normalization():
    env = OPERA_ADAPTER.normalize(
        CanonicalEntity.GUEST.value, "get_guest_profile", _load("opera", "get_guest_profile")
    )
    assert env["entity"] == "guest"
    assert env["items"] == [
        {
            "guest_id": "P-777",
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+15551234567",
        }
    ]


def test_opera_room_normalization():
    env = OPERA_ADAPTER.normalize(
        CanonicalEntity.ROOM.value, "get_room_types", _load("opera", "get_room_types")
    )
    assert env["entity"] == "room"
    assert env["items"][0] == {
        "room_type_code": "DLX",
        "name": "Deluxe Room",
        "description": "Deluxe Room",
        "max_occupancy": 3,
    }
    assert len(env["items"]) == 2


def test_opera_rate_plan_normalization():
    env = OPERA_ADAPTER.normalize(
        CanonicalEntity.RATE_PLAN.value, "get_rate_plans", _load("opera", "get_rate_plans")
    )
    assert env["entity"] == "rate_plan"
    assert env["items"] == [
        {
            "rate_plan_code": "BAR",
            "name": "Best Available Rate",
            "description": "Flexible rate, cancel up to 24h before arrival",
            "currency": "USD",
        }
    ]


# --- Totality: bad shapes return None/[] per contract, never raise ----------
def test_absent_wrapper_key_is_not_canonicalized():
    # No recognizable wrapper key -> "not canonicalized" (None), so a vendor shape
    # drift surfaces as unset rather than a misleading "zero records".
    for absent in ({}, {"unexpected": "shape"}):
        assert (
            OPERA_ADAPTER.normalize(CanonicalEntity.RESERVATION.value, "get_reservation", absent)
            is None
        )
    assert (
        GUESTCENTRIC_ADAPTER.normalize(CanonicalEntity.RESERVATION.value, "view_reservation", {})
        is None
    )
    assert (
        GUESTCENTRIC_ADAPTER.normalize(CanonicalEntity.AVAILABILITY.value, "hotel_rooms", {})
        is None
    )


def test_present_but_empty_wrapper_is_zero_records():
    # Wrapper present but malformed/empty inside -> canonicalized, zero records ([]).
    for empty in ({"reservations": None}, {"reservations": {}}, {"reservations": {"reservationInfo": []}}):
        env = OPERA_ADAPTER.normalize(CanonicalEntity.RESERVATION.value, "get_reservation", empty)
        assert env is not None and env["items"] == []

    gc = GUESTCENTRIC_ADAPTER.normalize(
        CanonicalEntity.RESERVATION.value, "view_reservation", {"reservations": []}
    )
    assert gc is not None and gc["items"] == []


def test_non_dict_bodies_opt_out():
    # Non-dict raw bodies (e.g. a bare list or string) opt out entirely.
    assert OPERA_ADAPTER.normalize(CanonicalEntity.RESERVATION.value, "x", []) is None
    assert GUESTCENTRIC_ADAPTER.normalize(CanonicalEntity.AVAILABILITY.value, "x", "oops") is None


def test_comp_reservation_preserves_zero_total():
    # A free/comp stay (total 0.0) must survive as 0.0, not be coalesced to None.
    gc = GUESTCENTRIC_ADAPTER.normalize(
        CanonicalEntity.RESERVATION.value,
        "view_reservation",
        {"reservations": [{"hotel_reservation_code": "R-0", "room_rate": {"total_price": 0.0}}]},
    )
    assert gc["items"][0]["total_amount"] == 0.0


def test_unknown_entity_returns_none():
    assert OPERA_ADAPTER.normalize("not_a_real_entity", "x", {"reservations": {}}) is None
    # GuestCentric only canonicalizes reservation + availability.
    assert GUESTCENTRIC_ADAPTER.normalize(
        CanonicalEntity.ROOM.value, "x", {"rooms": []}
    ) is None


def test_base_adapter_default_opts_out():
    from botelier.services.integration_runtime.adapters.base import DefaultAdapter

    assert DefaultAdapter().normalize(
        CanonicalEntity.RESERVATION.value, "x", {"reservations": {}}
    ) is None

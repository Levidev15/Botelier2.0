"""Canonical PMS domain schemas — a versioned, vendor-agnostic shared contract.

Different PMS/CRS vendors (Oracle Opera Cloud, GuestCentric, ...) return the same
business concepts in wildly different JSON shapes. The *canonical schemas* here are
the single vendor-neutral vocabulary the rest of Botelier can consume: once a
vendor response is normalized into these shapes, a consumer can no longer tell
which vendor produced the data.

Scope (Task #328): the PMS domain only — reservations, guests, rooms, rate plans,
and availability. Non-PMS domains are intentionally left out; add new entities by
extending :class:`CanonicalEntity` and adding a dataclass here (see
``docs-site/docs/integrations/canonical-domain-schemas.md``).

Hybrid design: canonicalization is OPT-IN per endpoint. Only endpoints tagged with
a ``canonical_entity`` in their seed produce canonical output; single-vendor and
custom endpoints keep using their per-endpoint ``response_mapping`` untouched.

Where normalization lives: INSIDE each vendor adapter (``adapters/opera_cloud.py``,
``adapters/guestcentric.py``). Vendor quirks stay contained in the adapter; this
module only owns the target shapes and the envelope they travel in.

Versioning policy — these shapes are a contract, treat them like a public API:
    * ADDING a new optional field is backwards-compatible; keep
      :data:`CANONICAL_SCHEMA_VERSION` the same.
    * RENAMING, REMOVING, or changing the type/meaning of an existing field is a
      BREAKING change: bump :data:`CANONICAL_SCHEMA_VERSION` and update every
      normalizer + consumer in lockstep. The version travels inside every envelope
      (:func:`build_envelope`) so consumers can branch on it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Optional

#: Bump ONLY on a breaking change to any canonical shape (see module docstring).
CANONICAL_SCHEMA_VERSION = "1"


class CanonicalEntity(str, Enum):
    """The PMS domain entities that can be canonicalized.

    The string values are exactly what a seed endpoint puts in its
    ``canonical_entity`` field, so the seed never needs to import this module.
    """

    RESERVATION = "reservation"
    GUEST = "guest"
    ROOM = "room"
    RATE_PLAN = "rate_plan"
    AVAILABILITY = "availability"


class ReservationStatus(str, Enum):
    """Vendor-neutral reservation lifecycle vocabulary.

    Each adapter maps its own vendor status strings onto these values so a
    consumer sees one consistent set regardless of provider.
    """

    CONFIRMED = "confirmed"
    IN_HOUSE = "in_house"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    WAITLISTED = "waitlisted"
    UNKNOWN = "unknown"


@dataclass
class CanonicalReservation:
    reservation_id: Optional[str] = None
    confirmation_number: Optional[str] = None
    status: Optional[str] = None
    guest_first_name: Optional[str] = None
    guest_last_name: Optional[str] = None
    arrival_date: Optional[str] = None
    departure_date: Optional[str] = None
    room_type_code: Optional[str] = None
    rate_plan_code: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None


@dataclass
class CanonicalGuest:
    guest_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


@dataclass
class CanonicalRoom:
    room_type_code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    max_occupancy: Optional[int] = None


@dataclass
class CanonicalRatePlan:
    rate_plan_code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    currency: Optional[str] = None


@dataclass
class CanonicalAvailability:
    room_type_code: Optional[str] = None
    room_name: Optional[str] = None
    rate_plan_code: Optional[str] = None
    arrival_date: Optional[str] = None
    departure_date: Optional[str] = None
    available: Optional[bool] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None


def coerce_str(value: Any) -> Optional[str]:
    """Return a trimmed string, or None for missing/blank values.

    Numeric ids (e.g. an int ``12345``) become ``"12345"`` so the canonical
    ``*_id`` fields have a single, vendor-independent type.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def coerce_int(value: Any) -> Optional[int]:
    """Best-effort int coercion; None on anything non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; None on anything non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_envelope(entity: Any, items: list) -> dict:
    """Wrap normalized entity items in the versioned canonical envelope.

    The envelope is what an adapter's ``normalize()`` returns and what lands on
    ``APIResponse.canonical`` / ``ActionExecutionResult.canonical``::

        {"schema_version": "1", "entity": "reservation", "items": [ {...}, ... ]}

    An empty ``items`` list means "canonicalized successfully, no records"
    (e.g. a search with no matches). ``normalize()`` returning ``None`` instead
    means "not canonicalized" — the two are deliberately distinct.
    """
    entity_value = entity.value if isinstance(entity, CanonicalEntity) else str(entity)
    return {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "entity": entity_value,
        "items": [asdict(item) if is_dataclass(item) else item for item in items],
    }

"""Universal capability registry (Task #329).

Declares the abstract, vendor-neutral capabilities the AI can call
(``search_availability``, ``lookup_reservation``, ``book_reservation``,
``cancel_reservation``). A capability is a *promise* — "look up a reservation" —
independent of which PMS / provider ultimately serves it. At runtime the
:class:`~botelier.services.capabilities.resolver.CapabilityResolver` maps a
capability to the caller's property-scoped provider connection and translates
the vendor-neutral arguments to that vendor's endpoint variable keys.

Design rules:
- The AI only ever sees the capability name + these vendor-neutral parameters.
  Vendor names, endpoint ids, and vendor-specific variable keys never reach the
  LLM.
- Property-identity keys (``hotel_id`` / ``property_id`` / etc.) are deliberately
  NOT capability parameters — they are re-forced from the resolved connection's
  config by ``IntegrationClient`` (Task #327 ``PROPERTY_IDENTITY_KEYS``), so a
  caller / LLM can never redirect a request to another property.
- ``mutating`` marks write capabilities (book / cancel). It is the single source
  of truth for the flow non-GET idempotency guard, which for capability nodes has
  no HTTP method to key off (the method lives on the resolved vendor endpoint).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CapabilitySpec:
    """A vendor-neutral capability the AI can invoke.

    Attributes:
        name: Stable capability identifier exposed to the LLM (e.g.
            ``"search_availability"``). Must be a valid OpenAI function name.
        description: Vendor-neutral description shown to the LLM.
        parameters: JSON-schema ``properties`` map of vendor-neutral arguments.
        required: Subset of ``parameters`` keys that are required.
        canonical_entity: The canonical domain entity the (read) capability
            returns, or ``None`` for write capabilities that return raw+mapped
            data only (Task #328 canonicalization is reads-only in v1).
        mutating: ``True`` for write capabilities (book / cancel). Drives the
            flow non-GET idempotency guard.
        service_backed: ``True`` for capabilities that do NOT resolve to a PMS
            vendor endpoint but are handled by a dedicated internal service
            (e.g. ``collect_payment`` → ``PaymentService``). The resolver routes
            these to their service instead of the ``resolve → IntegrationClient``
            path. Still property-scoped and idempotent like any other capability.
        required_permissions: Reserved for future per-capability RBAC. Empty in
            v1 — runtime capability calls run in an unauthenticated voice / SMS
            context; tool *configuration* is already permission-gated at the API
            edge.
    """

    name: str
    description: str
    parameters: Dict[str, Dict[str, Any]]
    required: List[str] = field(default_factory=list)
    canonical_entity: Optional[str] = None
    mutating: bool = False
    service_backed: bool = False
    required_permissions: List[str] = field(default_factory=list)

    def json_schema(self) -> Dict[str, Any]:
        """Return the OpenAI-style ``parameters`` JSON schema object."""
        return {
            "type": "object",
            "properties": dict(self.parameters),
            "required": list(self.required),
        }


# ---------------------------------------------------------------------------
# The capability registry.
#
# NOTE on write capabilities: booking is not perfectly vendor-neutral in v1.
# GuestCentric's book endpoint additionally requires rate / cancellation-policy /
# meal-plan identifiers that only exist AFTER a prior availability lookup, plus
# guest contact fields. Those are intentionally left OUT of the capability
# parameters: in a flow they are collected as slots (and passed through the
# resolver untranslated), and a standalone book against GuestCentric that lacks
# them fails explicitly (missing-variable error) rather than silently. Opera's
# create_reservation is satisfiable from the parameters below. This limitation is
# documented for consumers; search_availability / lookup_reservation are fully
# vendor-neutral across both providers.
# ---------------------------------------------------------------------------
_CAPABILITIES: Dict[str, CapabilitySpec] = {
    "search_availability": CapabilitySpec(
        name="search_availability",
        description=(
            "Search for available rooms / rates for a stay. Use when the caller "
            "wants to know what is available or how much a stay costs. Returns "
            "available room options with pricing."
        ),
        parameters={
            "check_in_date": {
                "type": "string",
                "description": "Arrival date in YYYY-MM-DD format.",
            },
            "check_out_date": {
                "type": "string",
                "description": "Departure date in YYYY-MM-DD format.",
            },
            "guest_count": {
                "type": "integer",
                "description": "Number of adult guests.",
            },
            "children": {
                "type": "integer",
                "description": "Number of children.",
            },
        },
        required=["check_in_date", "check_out_date"],
        canonical_entity="availability",
        mutating=False,
    ),
    "lookup_reservation": CapabilitySpec(
        name="lookup_reservation",
        description=(
            "Look up an existing reservation by its confirmation number. Use when "
            "the caller references a booking they already have."
        ),
        parameters={
            "confirmation_number": {
                "type": "string",
                "description": "The reservation confirmation number the caller provides.",
            },
        },
        required=["confirmation_number"],
        canonical_entity="reservation",
        mutating=False,
    ),
    "book_reservation": CapabilitySpec(
        name="book_reservation",
        description=(
            "Create a new reservation for the caller. Use only after the caller "
            "has chosen dates and a room, and provided their name. Confirm the "
            "details with the caller before calling this."
        ),
        parameters={
            "guest_first_name": {
                "type": "string",
                "description": "Guest first name.",
            },
            "guest_last_name": {
                "type": "string",
                "description": "Guest last name.",
            },
            "check_in_date": {
                "type": "string",
                "description": "Arrival date in YYYY-MM-DD format.",
            },
            "check_out_date": {
                "type": "string",
                "description": "Departure date in YYYY-MM-DD format.",
            },
            "room_type": {
                "type": "string",
                "description": "The room type / room type code the caller selected.",
            },
            "rate_code": {
                "type": "string",
                "description": "The rate plan code for the selected room.",
            },
            "guest_count": {
                "type": "integer",
                "description": "Number of adult guests.",
            },
            "children": {
                "type": "integer",
                "description": "Number of children.",
            },
        },
        required=[
            "guest_first_name",
            "guest_last_name",
            "check_in_date",
            "check_out_date",
            "room_type",
            "rate_code",
        ],
        canonical_entity=None,
        mutating=True,
    ),
    "cancel_reservation": CapabilitySpec(
        name="cancel_reservation",
        description=(
            "Cancel an existing reservation by its confirmation number. Confirm "
            "the caller really wants to cancel before calling this."
        ),
        parameters={
            "confirmation_number": {
                "type": "string",
                "description": "The confirmation number of the reservation to cancel.",
            },
        },
        required=["confirmation_number"],
        canonical_entity=None,
        mutating=True,
    ),
    "collect_payment": CapabilitySpec(
        name="collect_payment",
        description=(
            "Request a payment from the caller by sending them a secure payment "
            "link (for example by text message). Use when a deposit or payment is "
            "required — e.g. to hold a reservation. You NEVER handle card numbers "
            "yourself; the caller enters their card on a secure page. Provide the "
            "amount to charge."
        ),
        parameters={
            "amount": {
                "type": "number",
                "description": (
                    "The amount to charge in the property's currency, e.g. 149.00."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Short description of what the payment is for, e.g. "
                    "'Deposit for reservation'."
                ),
            },
            "reference": {
                "type": "string",
                "description": (
                    "Optional booking or confirmation reference to associate with "
                    "the payment."
                ),
            },
        },
        required=["amount"],
        canonical_entity=None,
        mutating=True,
        service_backed=True,
    ),
}


def get_capability(name: Optional[str]) -> Optional[CapabilitySpec]:
    """Return the :class:`CapabilitySpec` for ``name`` or ``None`` if unknown."""
    if not name:
        return None
    return _CAPABILITIES.get(name)


def all_capabilities() -> List[CapabilitySpec]:
    """Return every registered capability (stable order)."""
    return list(_CAPABILITIES.values())


def capability_names() -> List[str]:
    """Return every registered capability name."""
    return list(_CAPABILITIES.keys())


def build_capability_schema(name: str) -> Optional[Dict[str, Any]]:
    """Build the bare function schema (``{name, description, parameters}``).

    Voice (Pipecat) consumes this bare shape directly; SMS and the simulator
    wrap it in the OpenAI ``{"type": "function", "function": {...}}`` envelope.
    Returns ``None`` for an unknown capability so callers fail closed.
    """
    spec = get_capability(name)
    if spec is None:
        return None
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.json_schema(),
    }

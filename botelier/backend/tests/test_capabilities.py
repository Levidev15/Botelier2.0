"""Universal capability layer tests (Task #329).

Two layers:

  • Pure-logic: the registry (schema shape, mutating flags, canonical entity),
    argument translation, result formatting, and the shared property-access
    predicate — no DB.
  • DB-backed (like ``test_property_binding_api.py``): the runtime resolver's
    fail-closed selection — property-bound preference, ambiguous-tie rejection,
    cross-property rejection, unknown-capability rejection — against real
    ``AccountIntegration`` / ``IntegrationType`` rows, plus a parity check that the
    Opera + GuestCentric seeds carry the expected capability tags so the AI
    never sees a vendor.
"""

import os
import uuid

import pytest

from botelier.services.capabilities import (
    all_capabilities,
    build_capability_schema,
    capability_names,
    format_capability_result,
    get_capability,
)
from botelier.services.capabilities.resolver import CapabilityResolver, Resolution
from botelier.services.property_scope import property_access_allowed


# ── Registry (pure) ──────────────────────────────────────────────────────────


def test_registry_has_expected_capabilities():
    names = set(capability_names())
    assert names == {
        "search_availability",
        "lookup_reservation",
        "book_reservation",
        "cancel_reservation",
    }


def test_registry_mutating_and_canonical_flags():
    search = get_capability("search_availability")
    lookup = get_capability("lookup_reservation")
    book = get_capability("book_reservation")
    cancel = get_capability("cancel_reservation")

    # Reads are non-mutating and carry a canonical entity (Task #328 is reads-only).
    assert search.mutating is False and search.canonical_entity == "availability"
    assert lookup.mutating is False and lookup.canonical_entity == "reservation"
    # Writes are mutating and are NOT canonicalized in v1.
    assert book.mutating is True and book.canonical_entity is None
    assert cancel.mutating is True and cancel.canonical_entity is None


def test_build_capability_schema_is_bare_shape():
    schema = build_capability_schema("search_availability")
    assert set(schema.keys()) == {"name", "description", "parameters"}
    assert schema["name"] == "search_availability"
    params = schema["parameters"]
    assert params["type"] == "object"
    assert "check_in_date" in params["properties"]
    assert "check_in_date" in params["required"]


def test_build_capability_schema_never_leaks_vendor_terms():
    # The LLM-facing schema must be vendor-neutral: no vendor variable keys.
    for spec in all_capabilities():
        schema = build_capability_schema(spec.name)
        blob = str(schema).lower()
        for vendor_term in ("checkin", "crs_reservation_code", "rate_plan_code", "opera", "guestcentric"):
            assert vendor_term not in blob, f"{spec.name} leaked '{vendor_term}'"


def test_build_capability_schema_unknown_returns_none():
    assert build_capability_schema("nope") is None
    assert get_capability("nope") is None
    assert get_capability(None) is None


# ── property_access_allowed (pure) ───────────────────────────────────────────


def test_property_access_allowed_matrix():
    # Legacy session (no property) → allow anything.
    assert property_access_allowed(None, None) is True
    assert property_access_allowed(None, "prop-a") is True
    # Account-global integration (NULL) → always allowed.
    assert property_access_allowed("prop-a", None) is True
    # Matching property → allowed.
    assert property_access_allowed("prop-a", "prop-a") is True
    # Cross-property → rejected (fail closed).
    assert property_access_allowed("prop-a", "prop-b") is False


# ── translate_variables (pure) ───────────────────────────────────────────────


def _resolution(capability_params):
    return Resolution(
        integration_id="i-1",
        integration_property_id=None,
        endpoint_id="e-1",
        method="GET",
        capability_params=capability_params,
    )


def test_translate_variables_maps_and_passes_through():
    res = _resolution({"check_in_date": "checkin", "guest_count": "adults"})
    out = CapabilityResolver(db=None, account_id="a").translate_variables(
        res, {"check_in_date": "2026-01-01", "guest_count": 2, "notes": "late"}
    )
    # Canonical keys are translated to vendor keys...
    assert out["checkin"] == "2026-01-01"
    assert out["adults"] == 2
    # ...and unmapped keys pass through unchanged (vendor-specific slots survive).
    assert out["notes"] == "late"


def test_translate_variables_identity_when_no_mapping():
    res = _resolution({"confirmation_number": "confirmation_number"})
    out = CapabilityResolver(db=None, account_id="a").translate_variables(
        res, {"confirmation_number": "ABC123"}
    )
    assert out["confirmation_number"] == "ABC123"


# ── format_capability_result (pure) ──────────────────────────────────────────


class _Result:
    def __init__(self, **kw):
        self.success = kw.get("success", False)
        self.status_code = kw.get("status_code", 0)
        self.data = kw.get("data")
        self.error_type = kw.get("error_type")
        self.error_message = kw.get("error_message")
        self.extracted_variables = kw.get("extracted_variables", {})
        self.canonical = kw.get("canonical")


def test_format_result_success_prefers_canonical():
    out = format_capability_result(
        _Result(success=True, status_code=200, canonical={"entity": "availability", "items": []},
                extracted_variables={"x": 1})
    )
    assert out["canonical"] == {"entity": "availability", "items": []}
    assert out["data"] == {"x": 1}
    assert "error" not in out


def test_format_result_failure_shape():
    class _ET:
        value = "not_found"

    out = format_capability_result(
        _Result(success=False, status_code=404, error_type=_ET(), error_message="nope")
    )
    assert out["status"] == "failed"
    assert out["error"] == "nope"
    assert out["error_type"] == "not_found"
    assert out["status_code"] == 404


# ── Seed parity (pure) ───────────────────────────────────────────────────────


def _endpoints_by_capability(endpoints):
    out = {}
    for ep in endpoints:
        cap = ep.get("capability")
        if cap:
            out.setdefault(cap, []).append(ep)
    return out


def test_opera_seed_capability_tags():
    from botelier.seeds.opera_integration import OPERA_CLOUD_INTEGRATION

    by_cap = _endpoints_by_capability(OPERA_CLOUD_INTEGRATION["endpoints"])
    assert "search_availability" in by_cap
    assert "lookup_reservation" in by_cap
    assert "book_reservation" in by_cap
    # Opera has no cancel endpoint — capability simply won't resolve there.
    search = by_cap["search_availability"][0]
    assert search["capability_params"]["check_in_date"] == "check_in_date"


def test_guestcentric_seed_capability_tags_and_translation():
    from botelier.seeds.guestcentric_integration import GUESTCENTRIC_INTEGRATION

    by_cap = _endpoints_by_capability(GUESTCENTRIC_INTEGRATION["endpoints"])
    assert {"search_availability", "lookup_reservation", "book_reservation", "cancel_reservation"} <= set(
        by_cap.keys()
    )
    # GuestCentric renames the canonical keys to its own — proving the AI stays
    # vendor-neutral while the resolver bridges the gap.
    search = by_cap["search_availability"][0]
    assert search["capability_params"]["check_in_date"] == "checkin"
    assert search["capability_params"]["guest_count"] == "adults"
    cancel = by_cap["cancel_reservation"][0]
    assert cancel["capability_params"]["confirmation_number"] == "crs_reservation_code"


# ── Resolver selection (DB-backed) ───────────────────────────────────────────

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_capabilities requires DATABASE_URL to be set. The resolver "
        "selection tests are DB-backed and must not be silently skipped — point "
        "DATABASE_URL at a test or dev database."
    )

from botelier.database import SessionLocal  # noqa: E402
from botelier.models.account import Account, AccountStatus, SubscriptionTier  # noqa: E402
from botelier.models.integration import (  # noqa: E402
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.property import Property  # noqa: E402

_SEARCH_ENDPOINTS = [
    {
        "id": "search",
        "capability": "search_availability",
        "capability_params": {"check_in_date": "check_in_date"},
        "method": "GET",
        "path": "/search",
    }
]


def _make_account(db):
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"cap-{suffix}",
        slug=f"cap-{suffix}",
        email=f"cap-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_itype(db, endpoints):
    itype = IntegrationType(
        slug=f"cap-type-{uuid.uuid4().hex[:8]}",
        name="Cap Test Type",
        provider="test",
        auth_type="none",
    )
    itype.set_endpoints(endpoints)
    db.add(itype)
    db.flush()
    return itype


def _make_integration(db, account_id, itype_id, property_id, status=IntegrationStatus.CONNECTED):
    integ = AccountIntegration(
        account_id=account_id,
        integration_type_id=itype_id,
        property_id=property_id,
        status=status,
    )
    db.add(integ)
    db.flush()
    return integ


@pytest.fixture()
def env():
    db = SessionLocal()
    created = []
    try:
        acct = _make_account(db)
        prop_a = _make_property = Property(account_id=acct.id, name="Hotel A")
        prop_b = Property(account_id=acct.id, name="Hotel B")
        db.add_all([prop_a, prop_b])
        db.flush()
        created.append((db, acct, prop_a, prop_b))
        yield db, acct, prop_a, prop_b
    finally:
        db.rollback()
        db.close()


def test_resolver_property_bound_preferred_over_global(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _SEARCH_ENDPOINTS)
    # One account-global connection and one bound to property A.
    _make_integration(db, acct.id, itype.id, property_id=None)
    bound = _make_integration(db, acct.id, itype.id, property_id=prop_a.id)

    resolver = CapabilityResolver(db, str(acct.id), str(prop_a.id))
    res = resolver.resolve("search_availability")
    assert res is not None
    assert res.integration_id == str(bound.id)


def test_resolver_ambiguous_tie_fails_closed(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _SEARCH_ENDPOINTS)
    # Two account-global connections both serving the capability → ambiguous.
    _make_integration(db, acct.id, itype.id, property_id=None)
    _make_integration(db, acct.id, itype.id, property_id=None)

    # Legacy session (no property) sees both in the same tier → fail closed.
    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve("search_availability") is None


def test_resolver_cross_property_rejected(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _SEARCH_ENDPOINTS)
    # Only a property-B connection exists; a property-A session must not use it.
    _make_integration(db, acct.id, itype.id, property_id=prop_b.id)

    resolver = CapabilityResolver(db, str(acct.id), str(prop_a.id))
    assert resolver.resolve("search_availability") is None


def test_resolver_ignores_disconnected(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _SEARCH_ENDPOINTS)
    _make_integration(
        db, acct.id, itype.id, property_id=None, status=IntegrationStatus.DISCONNECTED
    )
    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve("search_availability") is None


def test_resolver_unknown_capability_returns_none(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _SEARCH_ENDPOINTS)
    _make_integration(db, acct.id, itype.id, property_id=None)
    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve("teleport_guest") is None

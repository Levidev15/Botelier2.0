"""PMS-native review+pay tests (Task #339).

Three layers, mirroring ``test_capabilities.py``:

  • Pure adapter: the card-capture validation contract — a booking+charge is
    never issued with an incomplete card (base), and GuestCentric additionally
    requires the rate/policy/meal-plan ids that only exist after an availability
    lookup.
  • Seed parity: the combined booking+payment endpoints carry
    ``supports_card_capture`` and deliberately have NO ``capability`` tag, so they
    never compete with plain ``book_reservation`` in the resolver.
  • Resolver selection (DB-backed): ``resolve_pms_native_payment`` uses the same
    fail-closed, property-tiered, ambiguity-refusing selection as ``resolve`` —
    ``None`` means fall back to the Stripe link rather than guess a provider.
"""

import os
import uuid

import pytest

from botelier.services.integration_runtime.adapters.base import DefaultAdapter
from botelier.services.integration_runtime.adapters.guestcentric import GuestCentricAdapter


# ── Adapter card-capture validation (pure) ───────────────────────────────────


def _full_card():
    return {
        "card_holder": "Ada Lovelace",
        "card_number": "4111111111111111",
        "card_expiry": "12/29",
        "card_cvv": "123",
    }


def test_base_validate_card_capture_accepts_full_card():
    DefaultAdapter().validate_card_capture(_full_card())


@pytest.mark.parametrize("missing", ["card_holder", "card_number", "card_expiry", "card_cvv"])
def test_base_validate_card_capture_rejects_missing_field(missing):
    card = _full_card()
    card[missing] = "   "
    with pytest.raises(ValueError) as exc:
        DefaultAdapter().validate_card_capture(card)
    assert missing in str(exc.value)


def test_base_validate_card_capture_rejects_empty_dict():
    with pytest.raises(ValueError):
        DefaultAdapter().validate_card_capture({})


def _gc_extra():
    return {
        "room_type_code": "DLX",
        "rate_plan_code": "BAR",
        "room_rate_code": "RC1",
        "total_price": "450.00",
        "cancellation_policy_id": "CP1",
        "meal_plan_id": "BB",
    }


def test_guestcentric_requires_card_and_booking_context():
    adapter = GuestCentricAdapter()
    # Card alone is not enough — GC needs the availability-derived ids too.
    with pytest.raises(ValueError) as exc:
        adapter.validate_card_capture(_full_card())
    msg = str(exc.value)
    assert "GuestCentric" in msg and "cancellation_policy_id" in msg


def test_guestcentric_accepts_card_plus_full_booking_context():
    adapter = GuestCentricAdapter()
    adapter.validate_card_capture({**_full_card(), **_gc_extra()})


def test_guestcentric_still_fails_on_missing_card_even_with_context():
    adapter = GuestCentricAdapter()
    card = _full_card()
    card["card_cvv"] = ""
    with pytest.raises(ValueError) as exc:
        adapter.validate_card_capture({**card, **_gc_extra()})
    assert "card_cvv" in str(exc.value)


# ── Seed parity (pure) ───────────────────────────────────────────────────────


def _card_capture_endpoints(spec):
    return [e for e in spec["endpoints"] if e.get("supports_card_capture")]


def test_opera_combined_endpoint_is_card_capture_not_a_capability():
    from botelier.seeds.opera_integration import OPERA_CLOUD_INTEGRATION

    eps = _card_capture_endpoints(OPERA_CLOUD_INTEGRATION)
    assert len(eps) == 1
    ep = eps[0]
    assert ep["id"] == "create_reservation_with_payment"
    # Must NOT compete with book_reservation in the capability resolver.
    assert ep.get("capability") is None
    assert (ep.get("method") or "").upper() == "POST"


def test_guestcentric_combined_endpoint_is_card_capture_not_a_capability():
    from botelier.seeds.guestcentric_integration import GUESTCENTRIC_INTEGRATION

    eps = _card_capture_endpoints(GUESTCENTRIC_INTEGRATION)
    assert len(eps) == 1
    ep = eps[0]
    assert ep["id"] == "book_reservation_with_payment"
    assert ep.get("capability") is None
    assert (ep.get("method") or "").upper() == "POST"


# ── Resolver selection (DB-backed) ───────────────────────────────────────────

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_pms_native_payment requires DATABASE_URL to be set. The resolver "
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
from botelier.services.capabilities.resolver import CapabilityResolver  # noqa: E402

_CARD_ENDPOINTS = [
    {
        "id": "create_reservation_with_payment",
        "supports_card_capture": True,
        "method": "POST",
        "path": "/book-and-pay",
    }
]


def _make_account(db):
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"pay-{suffix}",
        slug=f"pay-{suffix}",
        email=f"pay-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_itype(db, endpoints):
    itype = IntegrationType(
        slug=f"pay-type-{uuid.uuid4().hex[:8]}",
        name="Pay Test Type",
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
    try:
        acct = _make_account(db)
        prop_a = Property(account_id=acct.id, name="Hotel A")
        prop_b = Property(account_id=acct.id, name="Hotel B")
        db.add_all([prop_a, prop_b])
        db.flush()
        yield db, acct, prop_a, prop_b
    finally:
        db.rollback()
        db.close()


def test_pms_native_property_bound_preferred_over_global(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _CARD_ENDPOINTS)
    _make_integration(db, acct.id, itype.id, property_id=None)
    bound = _make_integration(db, acct.id, itype.id, property_id=prop_a.id)

    resolver = CapabilityResolver(db, str(acct.id), str(prop_a.id))
    res = resolver.resolve_pms_native_payment()
    assert res is not None
    assert res.integration_id == str(bound.id)
    assert res.endpoint_id == "create_reservation_with_payment"


def test_pms_native_ambiguous_tie_falls_back_to_link(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _CARD_ENDPOINTS)
    # Two account-global card-capture connections → ambiguous, refuse to guess.
    _make_integration(db, acct.id, itype.id, property_id=None)
    _make_integration(db, acct.id, itype.id, property_id=None)

    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve_pms_native_payment() is None


def test_pms_native_cross_property_rejected(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _CARD_ENDPOINTS)
    # Only property B has a card-capture connection; property A must not use it.
    _make_integration(db, acct.id, itype.id, property_id=prop_b.id)

    resolver = CapabilityResolver(db, str(acct.id), str(prop_a.id))
    assert resolver.resolve_pms_native_payment() is None


def test_pms_native_ignores_disconnected(env):
    db, acct, prop_a, prop_b = env
    itype = _make_itype(db, _CARD_ENDPOINTS)
    _make_integration(
        db, acct.id, itype.id, property_id=None, status=IntegrationStatus.DISCONNECTED
    )
    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve_pms_native_payment() is None


def test_pms_native_none_when_no_card_capture_endpoint(env):
    db, acct, prop_a, prop_b = env
    # A connected integration whose endpoint is NOT tagged supports_card_capture.
    itype = _make_itype(
        db, [{"id": "book", "capability": "book_reservation", "method": "POST", "path": "/book"}]
    )
    _make_integration(db, acct.id, itype.id, property_id=None)
    resolver = CapabilityResolver(db, str(acct.id), None)
    assert resolver.resolve_pms_native_payment() is None


# --------------------------------------------------------------------------- #
# Card data must never reach the logs, even on a malformed rendered body.       #
# --------------------------------------------------------------------------- #


def test_build_body_never_logs_card_on_malformed_json(caplog):
    """A body template that renders to invalid JSON must NOT log the rendered
    body — it can contain a PAN/CVV. Only the safe endpoint identity is logged.
    """
    import logging

    from botelier.services.integration_runtime.client import IntegrationClient
    from botelier.services.integration_runtime.types import IntegrationAPIConfig

    pan = "4111111111111111"
    cvv = "737"
    # Deliberately malformed JSON (trailing comma / unquoted) after substitution.
    config = IntegrationAPIConfig(
        integration_id="int-abc",
        endpoint_id="book_reservation_with_payment",
        body_template='{"card_number": {{card_number}}, "cvv": {{card_cvv}},}',
    )
    variables = {"card_number": pan, "card_cvv": cvv}

    client = IntegrationClient(account_id="acct-1")

    # loguru does not propagate to the stdlib logging caplog handler by default;
    # bridge it so caplog captures loguru output for this assertion.
    from loguru import logger as _loguru_logger

    handler_id = _loguru_logger.add(caplog.handler, format="{message}", level="DEBUG")
    try:
        with caplog.at_level(logging.DEBUG):
            result = client._build_body(config, variables)
    finally:
        _loguru_logger.remove(handler_id)

    assert result is None  # malformed JSON returns None
    combined = caplog.text + " ".join(r.getMessage() for r in caplog.records)
    assert pan not in combined, "PAN leaked into logs"
    assert cvv not in combined, "CVV leaked into logs"
    # The safe endpoint identity is still logged so the failure is diagnosable.
    assert "book_reservation_with_payment" in combined


# --------------------------------------------------------------------------- #
# Public review+pay submit flow: token lifecycle, double-submit race, scoping, #
# card non-persistence, and forged-completion rejection.                       #
# --------------------------------------------------------------------------- #

from botelier.models.payment import Payment, PaymentMethod, PaymentStatus  # noqa: E402
from botelier.services.action_executor import (  # noqa: E402
    ActionExecutionResult,
    ActionExecutor,
)
from botelier.services.integration_runtime.types import APIErrorType  # noqa: E402


class _FakeRequest:
    """Minimal stand-in for a Starlette Request carrying form data."""

    def __init__(self, form_data: dict):
        self._form_data = form_data

    async def form(self):
        from starlette.datastructures import FormData

        return FormData(list(self._form_data.items()))


def _make_pms_payment(db, account_id, property_id=None, **overrides):
    payment = Payment(
        account_id=account_id,
        property_id=property_id,
        idempotency_key=f"idem-{uuid.uuid4().hex}",
        status=PaymentStatus.PENDING,
        method=PaymentMethod.PMS_NATIVE,
        amount=250,
        currency="USD",
        link_token=f"tok-{uuid.uuid4().hex}",
        provider_refs={
            "pms_integration_id": str(uuid.uuid4()),
            "pms_endpoint_id": "create_reservation_with_payment",
            "pms_vendor_slug": "opera-cloud",
        },
    )
    for k, v in overrides.items():
        setattr(payment, k, v)
    db.add(payment)
    db.flush()
    return payment


def _card_form(**extra):
    form = {
        "card_holder": "Ada Lovelace",
        "card_number": "4111111111111111",
        "card_expiry": "12/29",
        "card_cvv": "737",
    }
    form.update(extra)
    return form


def _patch_executor(monkeypatch, result=None, captured=None, raises=None):
    async def _fake_execute_and_log(self, request):
        if captured is not None:
            captured["request"] = request
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(ActionExecutor, "execute_and_log", _fake_execute_and_log)


@pytest.mark.asyncio
async def test_submit_success_captures_and_burns_token(env, monkeypatch):
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(
            success=True,
            status_code=200,
            extracted_variables={"confirmation_number": "REAL123"},
        ),
    )

    resp = await review_submit(token, _FakeRequest(_card_form()), db)
    assert resp.status_code == 200

    db.refresh(payment)
    assert payment.status == PaymentStatus.CAPTURED
    assert payment.link_token is None  # single-use token burned
    assert payment.reference == "REAL123"


@pytest.mark.asyncio
async def test_submit_provider_decline_marks_failed_and_burns(env, monkeypatch):
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(
            success=False, status_code=502, error_type=APIErrorType.SERVER_ERROR
        ),
    )

    resp = await review_submit(token, _FakeRequest(_card_form()), db)
    assert resp.status_code == 502

    db.refresh(payment)
    assert payment.status == PaymentStatus.FAILED
    assert payment.link_token is None  # terminal → burned


@pytest.mark.asyncio
async def test_submit_double_submit_in_progress_is_not_terminal(env, monkeypatch):
    """The idempotency guard's status_code==0 'in progress' must NOT mark FAILED
    or burn the link — otherwise a stale double-submit clobbers the winning
    request's booking. Token stays alive; row stays PENDING.
    """
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(
            success=False,
            status_code=0,  # ActionExecutor._error → in-progress / replay guard
            error_type=APIErrorType.UNKNOWN,
            error_message="This request is already being processed.",
        ),
    )

    resp = await review_submit(token, _FakeRequest(_card_form()), db)
    assert resp.status_code == 409

    db.refresh(payment)
    assert payment.status == PaymentStatus.PENDING  # untouched
    assert payment.link_token == token  # NOT burned — winner may still capture


@pytest.mark.asyncio
async def test_submit_exception_marks_failed_and_burns(env, monkeypatch):
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    _patch_executor(monkeypatch, raises=RuntimeError("transport blew up"))

    resp = await review_submit(token, _FakeRequest(_card_form()), db)
    assert resp.status_code == 502

    db.refresh(payment)
    assert payment.status == PaymentStatus.FAILED
    assert payment.link_token is None


@pytest.mark.asyncio
async def test_submit_incomplete_card_is_terminal(env, monkeypatch):
    """A submit missing a card field (bypassed client-side `required`) is terminal:
    the link burns so it cannot be replayed, and no PMS call is issued.
    """
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    called = {"n": 0}

    async def _should_not_run(self, request):
        called["n"] += 1
        return ActionExecutionResult(success=True, status_code=200)

    monkeypatch.setattr(ActionExecutor, "execute_and_log", _should_not_run)

    form = _card_form()
    del form["card_cvv"]  # incomplete card
    resp = await review_submit(token, _FakeRequest(form), db)
    assert resp.status_code == 400
    assert called["n"] == 0  # PMS never called with an incomplete card

    db.refresh(payment)
    assert payment.status == PaymentStatus.FAILED
    assert payment.link_token is None


@pytest.mark.asyncio
async def test_submit_threads_property_scope_and_never_persists_card(env, monkeypatch):
    """The submit path carries the payment's property_id into the ActionContext
    (per-property isolation is enforced downstream in IntegrationClient), and no
    card data is ever written to the persisted Payment row.
    """
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token
    captured: dict = {}

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(
            success=True,
            status_code=200,
            extracted_variables={"confirmation_number": "REAL999"},
        ),
        captured=captured,
    )

    await review_submit(token, _FakeRequest(_card_form()), db)

    # Property scope threaded into the execution context.
    ctx = captured["request"].context
    assert ctx.property_id == str(prop_a.id)
    assert ctx.account_id == str(acct.id)
    # The card DID ride in-memory to the PMS call (that is the whole point)…
    assert captured["request"].variables.get("card_number") == "4111111111111111"

    # …but is NEVER persisted anywhere on the Payment row.
    db.refresh(payment)
    row_blob = " ".join(
        str(v) for v in (payment.reference, payment.description, payment.provider_refs)
    )
    assert "4111111111111111" not in row_blob
    assert "737" not in row_blob


@pytest.mark.asyncio
async def test_submit_ignores_forged_confirmation_from_form(env, monkeypatch):
    """A caller cannot forge the confirmation number by submitting it in the form;
    the reference is set only from the PMS result's extracted variables.
    """
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(
            success=True,
            status_code=200,
            extracted_variables={"confirmation_number": "REAL-FROM-PMS"},
        ),
    )

    form = _card_form(confirmation_number="FORGED-BY-CALLER")
    await review_submit(token, _FakeRequest(form), db)

    db.refresh(payment)
    assert payment.reference == "REAL-FROM-PMS"
    assert payment.reference != "FORGED-BY-CALLER"


@pytest.mark.asyncio
async def test_submit_already_consumed_token_returns_410(env, monkeypatch):
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(
        db, acct.id, prop_a.id, status=PaymentStatus.CAPTURED, link_token=None
    )
    # A caller replaying an old token value never resolves to an active payment.
    resp = await review_submit("tok-stale-value", _FakeRequest(_card_form()), db)
    assert resp.status_code == 410

    db.refresh(payment)
    assert payment.status == PaymentStatus.CAPTURED  # untouched


@pytest.mark.asyncio
async def test_submit_rejects_field_tampering(env, monkeypatch):
    """The submitted form is untrusted. A caller cannot overlay a non-editable
    field (``total_price``) or inject an extra vendor variable (``rate_id``) onto
    the combined booking+charge payload — only editable+visible design fields and
    card fields survive. An edit to a genuinely editable field DOES pass through.
    """
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token
    captured: dict = {}

    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(success=True, status_code=200),
        captured=captured,
    )

    form = _card_form(
        guest_first_name="Grace",       # editable+visible in default design → kept
        total_price="1",                # editable=False in default design → ignored
        rate_id="INJECTED-RATE",        # not in the template at all → ignored
    )
    await review_submit(token, _FakeRequest(form), db)

    variables = captured["request"].variables
    assert variables.get("guest_first_name") == "Grace"
    assert "total_price" not in variables       # non-editable field never overlaid
    assert "rate_id" not in variables           # injected vendor key dropped
    # Card fields (always allowed, never in the template's editable set) still ride.
    assert variables.get("card_number") == "4111111111111111"


@pytest.mark.asyncio
async def test_submit_hidden_field_cannot_be_edited(env, monkeypatch):
    """A field the operator hid (``visible: False``) can never be edited on submit
    even though its key exists in the design — a hidden field is not guest-editable.
    """
    from botelier.api import payments as payments_mod
    from botelier.api.payments import review_submit

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)
    token = payment.link_token
    captured: dict = {}

    design = {
        "branding": {},
        "sections": [
            {
                "id": "reservation",
                "fields": [
                    # editable but hidden → still not editable
                    {"key": "guest_email", "editable": True, "visible": False},
                ],
            },
            {
                "id": "payment",
                "fields": [
                    {"key": k, "editable": True, "visible": True}
                    for k in ("card_holder", "card_number", "card_expiry", "card_cvv")
                ],
            },
        ],
        "footer": {},
    }
    monkeypatch.setattr(payments_mod, "_effective_design", lambda *a, **k: design)
    _patch_executor(
        monkeypatch,
        result=ActionExecutionResult(success=True, status_code=200),
        captured=captured,
    )

    form = _card_form(guest_email="attacker@evil.test")
    await review_submit(token, _FakeRequest(form), db)

    assert "guest_email" not in captured["request"].variables


def test_validate_design_rejects_unsafe_branding():
    """Unsafe colors and non-http(s) URLs are rejected at API write time."""
    from botelier.models.payment_page_template import validate_design

    with pytest.raises(ValueError):
        validate_design({"branding": {"primary_color": "red; } body { x"}})
    with pytest.raises(ValueError):
        validate_design({"branding": {"accent_color": "#zzzzzz"}})
    with pytest.raises(ValueError):
        validate_design({"branding": {"logo_url": "javascript:alert(1)"}})
    with pytest.raises(ValueError):
        validate_design({"footer": {"privacy_url": "javascript:alert(1)"}})
    # A valid design passes cleanly.
    validate_design(
        {
            "branding": {
                "primary_color": "#1a1a1a",
                "accent_color": "#4f7cff",
                "logo_url": "https://cdn.example.com/logo.png",
            },
            "footer": {"privacy_url": "https://example.com/privacy"},
        }
    )


def test_render_review_page_coerces_unsafe_branding(env):
    """Defense in depth: even if an unsafe value reaches the renderer (legacy row /
    non-validated write path), it can never break out of the CSS/href sink.
    """
    from botelier.api.payments import _render_review_page

    db, acct, prop_a, _ = env
    payment = _make_pms_payment(db, acct.id, prop_a.id)

    malicious = {
        "branding": {
            "primary_color": "red; } body { background:url(javascript:alert(1)); }",
            "accent_color": "#4f7cff",
            "logo_url": "javascript:alert('logo')",
        },
        "sections": [],
        "footer": {
            "privacy_url": "javascript:alert('privacy')",
            "terms_url": "https://example.com/terms",
        },
    }
    html_out = _render_review_page(payment, malicious, {})

    assert "javascript:alert" not in html_out          # no script-scheme URL sink
    assert "body { background" not in html_out          # CSS breakout coerced away
    assert "--primary: #1a1a1a" in html_out             # coerced to safe default
    assert "https://example.com/terms" in html_out      # valid URL preserved

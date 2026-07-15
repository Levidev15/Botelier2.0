"""Payments API (Task #330).

Two PUBLIC surfaces for the ``collect_payment`` capability's SMS-link method:

- ``POST /api/payments/webhook`` — processor completion callback. A forged
  completion would be a free booking, so the signature MUST verify before the
  payment is marked captured. Fails closed (HTTP 400) on any missing/invalid
  signature — including when no processor is configured (the v1 stub).
- ``GET /api/payments/pay/{link_token}`` — the customer-facing link embedded in
  the SMS. Looks up the single-use token and redirects to the processor's hosted
  checkout. Unknown / expired / consumed tokens fail closed.

Neither route trusts the caller's identity: the webhook trusts only a verified
signature, and the pay link trusts only an unguessable single-use token.
"""

import html
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.payment import Payment, PaymentMethod, PaymentStatus
from botelier.models.payment_page_template import (
    PaymentPageTemplate,
    default_page_design,
    safe_color,
    safe_url,
)
from botelier.services.payments import get_payment_provider
from botelier.services.payments.providers import PaymentProviderError
from botelier.services.payments.service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

# Card fields are NEVER persisted or logged — they exist only in the request that
# forwards them to the PMS. Kept here so the submit path can strip them out of any
# value that would otherwise be echoed back or stored.
_CARD_FIELD_KEYS = ("card_holder", "card_number", "card_expiry", "card_cvv")


def _editable_field_keys(design: dict) -> set:
    """Server-side allowlist of keys a guest may edit/supply on submit.

    A submitted form is untrusted: without this gate a caller could overlay
    ANY key (a hidden/readonly field like ``total_price``, or an injected vendor
    variable such as a rate/policy id) onto the combined booking+charge payload.
    The allowlist is derived from the operator's resolved design contract — a
    non-card field is editable only if it is BOTH ``editable`` and ``visible``
    (a hidden field can never be edited) — plus the card fields (which are never
    pre-filled and always come from the form). Every other submitted key is
    ignored and the authoritative AI-collected value is used instead.
    """
    keys = set(_CARD_FIELD_KEYS)
    for section in (design.get("sections") or []):
        for field in (section.get("fields") or []):
            key = str(field.get("key") or "")
            if not key or key in _CARD_FIELD_KEYS:
                continue
            if field.get("editable", True) is not False and field.get(
                "visible", True
            ) is not False:
                keys.add(key)
    return keys


# Common processor signature header names, checked in order.
_SIGNATURE_HEADERS = (
    "stripe-signature",
    "x-signature",
    "x-webhook-signature",
)


def _extract_signature(request: Request):
    for name in _SIGNATURE_HEADERS:
        value = request.headers.get(name)
        if value:
            return value
    return None


@router.post("/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    """Processor completion callback. Fail closed unless the signature verifies."""
    payload = await request.body()
    signature = _extract_signature(request)

    # v1: no per-account provider dispatch yet — the platform-level provider (stub
    # until a processor is connected) authenticates the event. An unconfigured
    # provider verifies nothing, so every unauthenticated webhook is rejected.
    provider = get_payment_provider(db, None, None)
    if not provider.verify_webhook(payload=payload, signature=signature):
        logger.warning("payment webhook rejected: signature verification failed")
        return Response(status_code=400, content="invalid signature")

    try:
        event = provider.parse_event(payload)
    except PaymentProviderError as exc:
        logger.warning("payment webhook parse failed: %s", exc)
        return Response(status_code=400, content="unparseable event")

    # Locate the payment by the processor reference, then apply within its tenant.
    payment = (
        db.query(Payment)
        .filter(Payment.provider_refs["provider_ref"].astext == event.provider_ref)
        .one_or_none()
    )
    if payment is None:
        logger.warning("payment webhook: no matching payment for event")
        # 200 so the processor stops retrying an event we cannot match.
        return Response(status_code=200, content="no matching payment")

    service = PaymentService(str(payment.account_id), payment.property_id and str(payment.property_id))
    service.apply_event(event.provider_ref, event.status)
    return Response(status_code=200, content="ok")


@router.get("/pay/{link_token}")
async def payment_link(link_token: str, db: Session = Depends(get_db)):
    """Customer-facing single-use payment link → redirect to hosted checkout."""
    payment = (
        db.query(Payment).filter(Payment.link_token == link_token).one_or_none()
    )
    if payment is None:
        return HTMLResponse(
            status_code=404,
            content="<h1>Payment link not found</h1>",
        )

    if payment.status in (PaymentStatus.CAPTURED, PaymentStatus.FAILED, PaymentStatus.EXPIRED):
        return HTMLResponse(
            status_code=410,
            content="<h1>This payment link is no longer active.</h1>",
        )

    if payment.expires_at and payment.expires_at < datetime.utcnow():
        return HTMLResponse(
            status_code=410,
            content="<h1>This payment link has expired.</h1>",
        )

    # Task #339: a PMS-native payment renders our own review+pay page instead of
    # redirecting to a hosted checkout.
    if payment.method == PaymentMethod.PMS_NATIVE:
        return RedirectResponse(
            url=f"/api/payments/review/{link_token}", status_code=302
        )

    checkout_url = (payment.provider_refs or {}).get("checkout_url")
    if not checkout_url:
        return HTMLResponse(
            status_code=503,
            content="<h1>Payment is temporarily unavailable.</h1>",
        )

    return RedirectResponse(url=checkout_url, status_code=302)


# --------------------------------------------------------------------------- #
# Task #339 — PMS-native review + pay page (public, single-use token).         #
# --------------------------------------------------------------------------- #


def _effective_design(db: Session, payment: Payment) -> dict:
    """The property's saved page design, or the platform default."""
    q = db.query(PaymentPageTemplate).filter(
        PaymentPageTemplate.account_id == payment.account_id
    )
    if payment.property_id is None:
        row = q.filter(PaymentPageTemplate.property_id.is_(None)).first()
    else:
        row = (
            q.filter(PaymentPageTemplate.property_id == payment.property_id).first()
            or q.filter(PaymentPageTemplate.property_id.is_(None)).first()
        )
    if row is not None and row.design:
        return row.design
    return default_page_design()


def _prefill_slots(db: Session, payment: Payment) -> dict:
    """AI-collected reservation slots for this payment's flow session (scoped).

    Card fields are stripped defensively — a flow must never have collected card
    data, but the renderer guarantees it is never echoed into the page regardless.
    """
    from botelier.models.flow_session import FlowSession

    row = None
    if payment.flow_session_id is not None:
        row = (
            db.query(FlowSession)
            .filter(
                FlowSession.id == payment.flow_session_id,
                FlowSession.account_id == payment.account_id,
            )
            .first()
        )
    if row is None and payment.source_session_key:
        row = (
            db.query(FlowSession)
            .filter(
                FlowSession.account_id == payment.account_id,
                FlowSession.session_key == payment.source_session_key,
            )
            .order_by(FlowSession.updated_at.desc())
            .first()
        )
    slots = dict((row.collected_slots or {}) if row is not None else {})
    for key in _CARD_FIELD_KEYS:
        slots.pop(key, None)
    return slots


def _render_review_page(payment: Payment, design: dict, slots: dict) -> str:
    """Server-render the review+pay page from the operator's design contract."""
    branding = design.get("branding") or {}
    sections = design.get("sections") or []
    footer = design.get("footer") or {}

    # Coerce sink values at render (defense in depth on top of write-time
    # validation): unsafe colors/URLs can never reach the CSS `:root` or href/src.
    primary = safe_color(branding.get("primary_color"), "#1a1a1a")
    accent = safe_color(branding.get("accent_color"), "#4f7cff")
    heading = html.escape(branding.get("heading") or "Review & Pay")
    subheading = html.escape(branding.get("subheading") or "")
    logo_url = safe_url(branding.get("logo_url"))

    def field_html(field: dict) -> str:
        key = html.escape(str(field.get("key") or ""))
        label = html.escape(str(field.get("label") or key))
        editable = bool(field.get("editable", True))
        is_card = key in _CARD_FIELD_KEYS
        # Card fields are always empty (never pre-filled), always editable.
        raw_value = "" if is_card else slots.get(field.get("key"), "")
        value = html.escape("" if raw_value is None else str(raw_value))
        input_type = "text"
        attrs = f'name="{key}" value="{value}"'
        if is_card:
            # Card fields are required client-side so an incomplete card never
            # reaches the combined booking+charge call (server re-validates too).
            attrs = f'name="{key}" value="" autocomplete="off" required'
            if key == "card_number":
                input_type = "tel"
            elif key == "card_cvv":
                input_type = "tel"
        if not editable and not is_card:
            attrs += " readonly"
        return (
            f'<div class="field"><label>{label}</label>'
            f'<input type="{input_type}" {attrs} /></div>'
        )

    def is_visible(field: dict) -> bool:
        # A field is shown unless the operator explicitly hid it. Card fields can
        # never be hidden — a payment page without a card entry is meaningless.
        if str(field.get("key") or "") in _CARD_FIELD_KEYS:
            return True
        return bool(field.get("visible", True))

    sections_html = ""
    for section in sections:
        title = html.escape(str(section.get("title") or ""))
        fields = [f for f in (section.get("fields") or []) if is_visible(f)]
        if not fields:
            continue
        fields_html = "".join(field_html(f) for f in fields)
        sections_html += (
            f'<section><h2>{title}</h2><div class="grid">{fields_html}</div></section>'
        )

    amount = payment.amount
    currency = payment.currency or "USD"
    amount_str = f"${amount:.2f}" if currency == "USD" else f"{amount:.2f} {currency}"

    footer_links = []
    privacy_url = safe_url(footer.get("privacy_url"))
    terms_url = safe_url(footer.get("terms_url"))
    if privacy_url:
        footer_links.append(
            f'<a href="{html.escape(privacy_url)}" target="_blank" rel="noopener">Privacy Policy</a>'
        )
    if terms_url:
        footer_links.append(
            f'<a href="{html.escape(terms_url)}" target="_blank" rel="noopener">Terms</a>'
        )
    powered = (
        '<div class="powered">Powered by Botelier</div>'
        if footer.get("show_powered_by", True)
        else ""
    )
    logo_html = (
        f'<img class="logo" src="{html.escape(logo_url)}" alt="logo" />'
        if logo_url
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>{heading}</title>
<style>
  :root {{ --primary: {primary}; --accent: {accent}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background:#f4f5f7; color:#1a1a1a; padding:24px; }}
  .card {{ max-width:560px; margin:0 auto; background:#fff; border-radius:16px;
          overflow:hidden; box-shadow:0 8px 30px rgba(0,0,0,.08); }}
  header {{ background:var(--primary); color:#fff; padding:28px 28px 24px; }}
  .logo {{ max-height:44px; margin-bottom:14px; display:block; }}
  header h1 {{ margin:0 0 6px; font-size:22px; }}
  header p {{ margin:0; opacity:.85; font-size:14px; }}
  form {{ padding:24px 28px; }}
  section {{ margin-bottom:22px; }}
  section h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.04em;
               color:#6b7280; margin:0 0 12px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .field {{ display:flex; flex-direction:column; }}
  .field label {{ font-size:12px; color:#6b7280; margin-bottom:4px; }}
  .field input {{ padding:10px 12px; border:1px solid #d1d5db; border-radius:8px;
                  font-size:14px; }}
  .field input[readonly] {{ background:#f3f4f6; color:#6b7280; }}
  .total {{ display:flex; justify-content:space-between; align-items:center;
            padding:14px 0; border-top:1px solid #eee; font-size:18px;
            font-weight:600; margin-bottom:8px; }}
  button {{ width:100%; padding:14px; border:0; border-radius:10px;
            background:var(--accent); color:#fff; font-size:16px; font-weight:600;
            cursor:pointer; }}
  button:disabled {{ opacity:.6; cursor:default; }}
  .footer {{ text-align:center; padding:18px; font-size:12px; color:#9ca3af; }}
  .footer a {{ color:#6b7280; margin:0 8px; }}
  .powered {{ margin-top:8px; }}
  .msg {{ padding:12px; border-radius:8px; margin-bottom:12px; font-size:14px;
          display:none; }}
  .msg.err {{ background:#fee2e2; color:#991b1b; display:block; }}
  .secure {{ font-size:12px; color:#6b7280; text-align:center; margin-top:10px; }}
</style>
</head>
<body>
  <div class="card">
    <header>
      {logo_html}
      <h1>{heading}</h1>
      <p>{subheading}</p>
    </header>
    <form id="payform" method="post" action="/api/payments/review/{payment.link_token}/submit">
      <div class="msg" id="err"></div>
      {sections_html}
      <div class="total"><span>Total</span><span>{amount_str}</span></div>
      <button type="submit" id="submitBtn">Confirm &amp; Pay {amount_str}</button>
      <div class="secure">Your card is sent securely to the hotel's payment system. Botelier never stores your card.</div>
    </form>
    <div class="footer">
      <div>{''.join(footer_links)}</div>
      {powered}
    </div>
  </div>
<script>
  const form = document.getElementById('payform');
  const btn = document.getElementById('submitBtn');
  const err = document.getElementById('err');
  form.addEventListener('submit', async (e) => {{
    e.preventDefault();
    err.className = 'msg'; err.textContent = '';
    btn.disabled = true; btn.textContent = 'Processing…';
    try {{
      const res = await fetch(form.action, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
        body: new URLSearchParams(new FormData(form)),
      }});
      const data = await res.json().catch(() => ({{}}));
      if (res.ok && data.status === 'confirmed') {{
        document.querySelector('.card').innerHTML =
          '<header><h1>Payment confirmed</h1></header>' +
          '<div style="padding:28px;">' +
          '<p>Your reservation is confirmed.</p>' +
          (data.confirmation_number ? '<p><strong>Confirmation:</strong> ' +
            String(data.confirmation_number).replace(/[<>&]/g,'') + '</p>' : '') +
          '</div>';
      }} else {{
        err.className = 'msg err';
        err.textContent = (data && data.message) || 'We could not complete your payment. Please try again.';
        btn.disabled = false; btn.textContent = 'Confirm & Pay';
      }}
    }} catch (ex) {{
      err.className = 'msg err';
      err.textContent = 'Network error. Please try again.';
      btn.disabled = false; btn.textContent = 'Confirm & Pay';
    }}
  }});
</script>
</body>
</html>"""


def _load_active_pms_payment(db: Session, link_token: str):
    """Load a PMS-native payment by token, returning (payment, error_response)."""
    payment = (
        db.query(Payment).filter(Payment.link_token == link_token).one_or_none()
    )
    if payment is None or payment.method != PaymentMethod.PMS_NATIVE:
        return None, HTMLResponse(status_code=404, content="<h1>Payment link not found</h1>")
    if payment.status in (
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.EXPIRED,
    ):
        return None, HTMLResponse(
            status_code=410, content="<h1>This payment link is no longer active.</h1>"
        )
    if payment.expires_at and payment.expires_at < datetime.utcnow():
        return None, HTMLResponse(
            status_code=410, content="<h1>This payment link has expired.</h1>"
        )
    return payment, None


@router.get("/review/{link_token}")
async def review_page(link_token: str, db: Session = Depends(get_db)):
    """Render the single-use review+pay page for a PMS-native payment."""
    payment, error = _load_active_pms_payment(db, link_token)
    if error is not None:
        return error
    design = _effective_design(db, payment)
    slots = _prefill_slots(db, payment)
    return HTMLResponse(content=_render_review_page(payment, design, slots))


@router.post("/review/{link_token}/submit")
async def review_submit(link_token: str, request: Request, db: Session = Depends(get_db)):
    """Combined booking + card capture for a PMS-native payment (Task #339).

    ONE PMS call creates/confirms the reservation AND attaches the card so the
    hotel's own gateway charges it. The card is forwarded in-memory and never
    written to a Botelier log or DB row. Property-scoped and fail-closed via
    ``IntegrationClient``; single-use token is burned on success.
    """
    from fastapi.responses import JSONResponse

    payment, error = _load_active_pms_payment(db, link_token)
    if error is not None:
        # Token already consumed / expired — surface JSON for the page's fetch().
        return JSONResponse(status_code=410, content={"status": "failed", "message": "This payment link is no longer active."})

    refs = payment.provider_refs or {}
    integration_id = refs.get("pms_integration_id")
    endpoint_id = refs.get("pms_endpoint_id")
    vendor_slug = refs.get("pms_vendor_slug")
    if not integration_id or not endpoint_id:
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "message": "Payment is temporarily unavailable."},
        )

    def _fail_and_burn(status_code: int, message: str) -> "JSONResponse":
        """Mark the payment FAILED and invalidate the single-use link (#339 Step 6).

        A *terminal* outcome after the guest submits — a declined booking, a
        transport error, or an incomplete/invalid card — burns the token so the
        link can never be replayed. The caller is re-texted a fresh link (or
        falls back) rather than reusing a dead one.

        Concurrency: the transition is a guarded UPDATE that only fires while the
        row is still PENDING/AUTHORIZED. If a racing request already CAPTURED the
        payment (double-submit), this is a no-op — a stale in-flight request can
        never overwrite a confirmed booking with FAILED. Runs in the request's
        own session; a commit failure rolls back and leaves the row untouched.
        """
        try:
            updated = (
                db.query(Payment)
                .filter(
                    Payment.id == payment.id,
                    Payment.status.in_(
                        [PaymentStatus.PENDING, PaymentStatus.AUTHORIZED]
                    ),
                )
                .update(
                    {
                        Payment.status: PaymentStatus.FAILED,
                        Payment.link_token: None,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if updated == 0:
                logger.info(
                    "pms-native: payment %s already terminal; skipped FAILED transition",
                    payment.id,
                )
        except Exception as commit_exc:  # noqa: BLE001
            db.rollback()
            logger.error(
                "pms-native: could not mark payment %s failed: %s",
                payment.id,
                commit_exc,
            )
        return JSONResponse(
            status_code=status_code, content={"status": "failed", "message": message}
        )

    form = await request.form()
    submitted = {k: (v or "").strip() for k, v in form.items()}

    # Merge: AI-collected slots (authoritative vendor-keyed base) overlaid ONLY
    # with edits to keys the operator's design marks editable+visible, plus the
    # card fields. The submitted form is untrusted — a caller could otherwise
    # tamper with a readonly/hidden field (e.g. total_price) or inject an extra
    # vendor variable (e.g. a rate/policy id) into the booking+charge payload, so
    # any key not in the server-side allowlist is ignored and the AI-collected
    # value stands. Empty submitted values never overwrite a good collected value.
    design = _effective_design(db, payment)
    allowed_edit_keys = _editable_field_keys(design)
    merged = _prefill_slots(db, payment)
    for key, value in submitted.items():
        if value != "" and key in allowed_edit_keys:
            merged[key] = value

    # Fail loud if required card (and vendor-required booking) fields are missing —
    # never send an incomplete card to a gateway or silently create an unpaid stay.
    # The card inputs are `required` client-side, so a missing field here means a
    # bypassed form: treat it as terminal and burn the link.
    from botelier.services.integration_runtime.adapters.registry import resolve_adapter

    adapter = resolve_adapter(slug=vendor_slug)
    try:
        adapter.validate_card_capture(merged)
    except ValueError as exc:
        return _fail_and_burn(400, str(exc))

    from botelier.services.action_executor import (
        ActionContext,
        ActionExecutionRequest,
        ActionExecutor,
    )
    from botelier.services.integration_runtime.types import IntegrationAPIConfig

    config = IntegrationAPIConfig(
        integration_id=str(integration_id),
        endpoint_id=str(endpoint_id),
        method="POST",
    )
    exec_request = ActionExecutionRequest(
        context=ActionContext(
            account_id=str(payment.account_id),
            channel="payment_page",
            property_id=str(payment.property_id) if payment.property_id else None,
            source_label="pms_native_payment",
        ),
        variables=merged,
        integration_config=config,
        # Durable dedup so a double-submit cannot double-book/charge.
        idempotency_key=f"{payment.idempotency_key}:pms_submit",
        operation="book_reservation_with_payment",
    )

    try:
        result = await ActionExecutor(db).execute_and_log(exec_request)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the payer
        logger.error("pms-native submit failed for payment %s: %s", payment.id, exc)
        return _fail_and_burn(
            502, "We could not complete your payment. Please try again."
        )

    if not getattr(result, "success", False):
        result_status = getattr(result, "status_code", 0) or 0
        # A status_code of 0 is NOT a vendor decline — it is the idempotency guard
        # returning "already in progress" / ambiguous-replay / ledger-unavailable
        # (ActionExecutor._error). Treating it as terminal would let a stale
        # double-submit clobber a booking the winning request is about to CAPTURE.
        # Keep the link alive and tell the caller to wait; do NOT mark FAILED.
        if result_status == 0:
            logger.info(
                "pms-native submit for payment %s is an idempotent replay/in-progress; "
                "not terminal",
                payment.id,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "status": "processing",
                    "message": "This payment is already being processed. Please wait a moment.",
                },
            )
        logger.warning(
            "pms-native submit rejected for payment %s (status=%s)",
            payment.id,
            result_status,
        )
        return _fail_and_burn(
            502, "The hotel's system declined this booking. Please try again."
        )

    extracted = getattr(result, "extracted_variables", None) or {}
    confirmation = (
        extracted.get("confirmation_number")
        or extracted.get("crs_reservation_code")
        or extracted.get("hotel_reservation_code")
    )

    # Mark captured + burn the single-use token so the link cannot be replayed.
    payment.status = PaymentStatus.CAPTURED
    payment.link_token = None
    if confirmation:
        payment.reference = str(confirmation)[:128]
    db.commit()

    return JSONResponse(
        status_code=200,
        content={"status": "confirmed", "confirmation_number": confirmation},
    )

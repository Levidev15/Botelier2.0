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

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.payment import Payment, PaymentStatus
from botelier.services.payments import get_payment_provider
from botelier.services.payments.providers import PaymentProviderError
from botelier.services.payments.service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

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

    checkout_url = (payment.provider_refs or {}).get("checkout_url")
    if not checkout_url:
        return HTMLResponse(
            status_code=503,
            content="<h1>Payment is temporarily unavailable.</h1>",
        )

    return RedirectResponse(url=checkout_url, status_code=302)

"""PaymentService (Task #330).

Turns a vendor-neutral ``collect_payment`` capability call into a durable
``Payment`` record plus a processor checkout, and returns ONLY the AI-safe shape
``{status, payment_id, message}`` — never a processor identifier, checkout URL,
or link token.

Durability & idempotency:
- The service runs the payment record in its own isolated ``SessionLocal`` so a
  charge commits independently of the caller's (voice/SMS) transaction.
- ``payments.idempotency_key`` is UNIQUE, so a reconnect/retry of the same
  logical charge reuses the existing row instead of creating a second one — the
  row itself is the dedup boundary (belt-and-suspenders with the Task #330
  operation ledger).

Fail-closed: if no processor is configured for ``(account_id, property_id)`` the
service reports ``unavailable`` and creates no row — it never fakes a link.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from sqlalchemy.exc import IntegrityError

from botelier.config.domain import get_public_base_url
from botelier.models.payment import Payment, PaymentMethod, PaymentStatus
from botelier.services.payments.providers import (
    PaymentProviderError,
    get_payment_provider,
)

logger = logging.getLogger(__name__)


class PaymentService:
    # How long a minted payment link stays valid absent a provider expiry.
    LINK_TTL_SECONDS = 60 * 60

    def __init__(
        self,
        account_id: Optional[str],
        property_id: Optional[str] = None,
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        self.account_id = account_id
        self.property_id = property_id
        self._session_factory = session_factory

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from botelier.database import SessionLocal

        return SessionLocal()

    # -- public API ----------------------------------------------------------
    def collect_payment(
        self,
        *,
        amount: Any,
        currency: str = "USD",
        description: Optional[str] = None,
        reference: Optional[str] = None,
        channel: str = "voice",
        call_sid: Optional[str] = None,
        conversation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Create (or replay) a payment request. Returns the AI-facing shape."""
        if not self.account_id:
            return {"status": "failed", "message": "Payment requires account context."}

        amt = self._coerce_amount(amount)
        if amt is None or amt <= 0:
            return {
                "status": "failed",
                "message": "I couldn't process that amount. Please provide a valid amount.",
            }

        db = self._session()
        try:
            provider = get_payment_provider(db, self.account_id, self.property_id)
            if not provider.is_configured():
                logger.info(
                    "collect_payment unavailable — no processor (account=%s property=%s)",
                    self.account_id,
                    self.property_id,
                )
                return {
                    "status": "unavailable",
                    "message": "I'm not able to take a payment right now.",
                }

            # Durable dedup: a retry with the same key replays the existing row.
            if idempotency_key:
                existing = (
                    db.query(Payment)
                    .filter(Payment.idempotency_key == idempotency_key)
                    .one_or_none()
                )
                if existing is not None:
                    return existing.ai_result(self._spoken(existing))

            link_token = secrets.token_urlsafe(32)
            payment = Payment(
                account_id=self.account_id,
                property_id=self.property_id,
                idempotency_key=idempotency_key or secrets.token_urlsafe(24),
                status=PaymentStatus.PENDING,
                method=PaymentMethod.SMS_LINK,
                amount=amt,
                currency=(currency or "USD").upper()[:3],
                description=(description or None),
                reference=(reference or None),
                link_token=link_token,
                expires_at=datetime.utcnow()
                + timedelta(seconds=self.LINK_TTL_SECONDS),
            )
            db.add(payment)
            try:
                db.flush()
            except IntegrityError:
                # Concurrent insert won the unique key — replay the winner.
                db.rollback()
                existing = (
                    db.query(Payment)
                    .filter(Payment.idempotency_key == idempotency_key)
                    .one_or_none()
                    if idempotency_key
                    else None
                )
                if existing is not None:
                    return existing.ai_result(self._spoken(existing))
                return {
                    "status": "failed",
                    "message": "I'm not able to take a payment right now.",
                }

            return_url = f"{get_public_base_url()}/api/payments/pay/{link_token}"
            try:
                checkout = provider.create_checkout(
                    amount=float(amt),
                    currency=payment.currency,
                    description=payment.description,
                    reference=payment.reference,
                    idempotency_key=payment.idempotency_key,
                    return_url=return_url,
                )
            except PaymentProviderError as exc:
                logger.warning("collect_payment provider error: %s", exc)
                payment.status = PaymentStatus.FAILED
                payment.provider_refs = {"error": str(exc)}
                db.commit()
                return payment.ai_result("I'm not able to take a payment right now.")

            # provider_refs is SERVER-ONLY — never surfaced to the LLM.
            payment.provider_refs = {
                "provider": provider.name,
                "provider_ref": checkout.provider_ref,
                "checkout_url": checkout.checkout_url,
            }
            if checkout.expires_at:
                payment.expires_at = checkout.expires_at
            db.commit()
            return payment.ai_result(self._spoken(payment))
        finally:
            db.close()

    def collect_payment_pms_native(
        self,
        *,
        amount: Any,
        currency: str = "USD",
        description: Optional[str] = None,
        reference: Optional[str] = None,
        channel: str = "voice",
        call_sid: Optional[str] = None,
        conversation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        pms_integration_id: str,
        pms_endpoint_id: str,
        pms_vendor_slug: Optional[str] = None,
        session_key: Optional[str] = None,
    ) -> dict:
        """Create (or replay) a PMS-native review+pay request (Task #339).

        Unlike :meth:`collect_payment` (Stripe hosted checkout), this mints a link
        to Botelier's own review+pay page. The card is captured there and, on
        submit, forwarded in-memory to the property's PCI-certified PMS in ONE
        combined booking+payment call — Botelier never stores or logs the card.

        ``provider_refs`` records only the SERVER-ONLY PMS endpoint binding needed
        to execute the combined call at submit time; it never holds card data.
        """
        if not self.account_id:
            return {"status": "failed", "message": "Payment requires account context."}

        amt = self._coerce_amount(amount)
        if amt is None or amt <= 0:
            return {
                "status": "failed",
                "message": "I couldn't process that amount. Please provide a valid amount.",
            }

        db = self._session()
        try:
            if idempotency_key:
                existing = (
                    db.query(Payment)
                    .filter(Payment.idempotency_key == idempotency_key)
                    .one_or_none()
                )
                if existing is not None:
                    return existing.ai_result(self._spoken(existing))

            flow_session_id = self._resolve_flow_session_id(db, session_key)

            link_token = secrets.token_urlsafe(32)
            payment = Payment(
                account_id=self.account_id,
                property_id=self.property_id,
                idempotency_key=idempotency_key or secrets.token_urlsafe(24),
                status=PaymentStatus.PENDING,
                method=PaymentMethod.PMS_NATIVE,
                amount=amt,
                currency=(currency or "USD").upper()[:3],
                description=(description or None),
                reference=(reference or None),
                link_token=link_token,
                flow_session_id=flow_session_id,
                source_session_key=(session_key or None),
                # SERVER-ONLY: which PMS endpoint the combined submit calls. No card.
                provider_refs={
                    "provider": "pms_native",
                    "pms_integration_id": str(pms_integration_id),
                    "pms_endpoint_id": str(pms_endpoint_id),
                    "pms_vendor_slug": pms_vendor_slug or None,
                },
                expires_at=datetime.utcnow()
                + timedelta(seconds=self.LINK_TTL_SECONDS),
            )
            db.add(payment)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(Payment)
                    .filter(Payment.idempotency_key == idempotency_key)
                    .one_or_none()
                    if idempotency_key
                    else None
                )
                if existing is not None:
                    return existing.ai_result(self._spoken(existing))
                return {
                    "status": "failed",
                    "message": "I'm not able to take a payment right now.",
                }
            return payment.ai_result(self._spoken(payment))
        finally:
            db.close()

    def _resolve_flow_session_id(self, db, session_key: Optional[str]):
        """Best-effort link the payment to the caller's live flow session.

        Scoped to this account (never cross-tenant). Returns None when there is no
        session yet — the renderer can still resolve later via
        ``source_session_key``.
        """
        if not session_key or not self.account_id:
            return None
        try:
            from botelier.models.flow_session import FlowSession

            q = db.query(FlowSession).filter(
                FlowSession.account_id == self.account_id,
                FlowSession.session_key == session_key,
            )
            row = q.order_by(FlowSession.updated_at.desc()).first()
            return row.id if row is not None else None
        except Exception as exc:  # noqa: BLE001 - linkage is best-effort
            logger.warning("pms-native: could not resolve flow session: %s", exc)
            return None

    # -- webhook completion --------------------------------------------------
    def apply_event(self, provider_ref: str, status: str) -> bool:
        """Apply a *verified* processor event to its payment row.

        Returns True if a matching pending/authorized payment was updated. The
        caller (webhook route) MUST have verified the signature before calling.
        """
        db = self._session()
        try:
            payment = (
                db.query(Payment)
                .filter(
                    Payment.account_id == self.account_id,
                    Payment.provider_refs["provider_ref"].astext == provider_ref,
                )
                .one_or_none()
            )
            if payment is None:
                logger.warning("payment webhook: no payment for provider_ref")
                return False
            if payment.status == PaymentStatus.CAPTURED:
                return True  # idempotent — already applied
            payment.status = status
            if status in (PaymentStatus.CAPTURED, PaymentStatus.EXPIRED):
                # Single-use: burn the link so it cannot be replayed.
                payment.link_token = None
            db.commit()
            return True
        except Exception as exc:  # noqa: BLE001 - webhook must not 500 on bookkeeping
            db.rollback()
            logger.error("payment webhook apply failed: %s", exc)
            return False
        finally:
            db.close()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _coerce_amount(amount: Any) -> Optional[Decimal]:
        try:
            return Decimal(str(amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def _spoken(self, payment: Payment) -> str:
        if payment.status == PaymentStatus.CAPTURED:
            return "Your payment has been received. Thank you."
        if payment.status in (PaymentStatus.FAILED, PaymentStatus.EXPIRED):
            return "I'm not able to take a payment right now."
        return (
            f"I've set up a secure payment link for {self._fmt(payment)}. "
            "You'll receive it so you can complete your payment."
        )

    @staticmethod
    def _fmt(payment: Payment) -> str:
        amount = payment.amount
        if payment.currency == "USD":
            return f"${amount:.2f}"
        return f"{amount:.2f} {payment.currency}"

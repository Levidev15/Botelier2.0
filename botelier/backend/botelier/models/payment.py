"""Payment Model - Durable payment records (Task #330).

A ``Payment`` is the durable server-side record of one request to collect money
from a caller. It is created by ``collect_payment`` (the vendor-neutral payment
capability) and is the single source of truth for that charge's lifecycle across
a websocket dropout / reconnect.

Security & isolation invariants:
- **Tenant/property scoped.** Every row carries ``account_id`` and the Task #327
  ``property_id`` and is only ever created after ``property_access_allowed`` has
  passed. Payment configuration is keyed ``(account_id, property_id)``.
- **``provider_refs`` is SERVER-ONLY.** Processor identifiers (checkout session
  ids, payment-intent ids, customer ids, etc.) live here and must NEVER appear in
  a tool result surfaced to the LLM. The AI only ever sees ``{status,
  payment_id, spoken message}``.
- **Never expose card data.** Raw PAN / CVV never touch this system — the caller
  enters card details on the processor's hosted page reached via ``link_token``.
- **``idempotency_key`` is UNIQUE** so a reconnect/retry of the same logical
  charge reuses the existing row instead of creating a second charge.
- **``link_token`` is UNIQUE and single-use** — the unguessable token embedded in
  the SMS payment link; consuming it (a completed/expired payment) must invalidate
  it so a leaked link cannot be replayed.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from botelier.database import Base


class PaymentStatus(str):
    """VARCHAR status namespace (not a native PG enum)."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    EXPIRED = "expired"


class PaymentMethod(str):
    """Capture method behind the one ``collect_payment`` capability."""

    # DTMF card capture over the phone. NOT feasible in v1 (the voice call is a
    # Pipecat media-stream, not a TwiML ``<Pay>`` session) — kept for the schema
    # so the capability can fail closed *to* the SMS link without a migration.
    TWILIO_PAY = "twilio_pay"
    # Text the caller a secure hosted-checkout link (Stripe fallback path).
    SMS_LINK = "sms_link"
    # Task #339: text the caller a secure review+pay link that captures the card
    # and forwards it, in one combined booking+payment call, to the property's
    # PCI-certified PMS (Opera OHIP / GuestCentric). Botelier never stores the
    # card — it is forwarded in-memory to the PMS as an authorised booking
    # channel. Selected when the caller's property has a payment-capable PMS
    # connection; otherwise the capability falls back to ``SMS_LINK``.
    PMS_NATIVE = "pms_native"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cross-session dedup: a reconnect/retry with the same key reuses this row.
    idempotency_key = Column(String(128), nullable=False, unique=True, index=True)

    status = Column(String(16), nullable=False, default=PaymentStatus.PENDING)
    method = Column(String(16), nullable=False, default=PaymentMethod.SMS_LINK)

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")

    description = Column(String(255), nullable=True)
    # Free-form business reference (e.g. reservation confirmation number).
    reference = Column(String(128), nullable=True)

    # SERVER-ONLY processor identifiers — never surfaced to the LLM.
    provider_refs = Column(JSONB, nullable=True)

    # Unguessable single-use token embedded in the payment link.
    link_token = Column(String(64), nullable=True, unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)

    # Provenance — which contact requested the charge (one is set per channel).
    source_call_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_conversation_id = Column(UUID(as_uuid=True), nullable=True)

    # Task #339: link back to the durable flow session whose collected slots the
    # AI captured, so the review+pay page can pre-fill the reservation. NULL for
    # legacy / Stripe-fallback payments. ``source_session_key`` is the channel's
    # stable contact id (call_sid / conversation id) used to resolve the session
    # at page-render time when the row was created before the session finalised.
    flow_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("flow_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_session_key = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_payments_account_property", "account_id", "property_id"),
        Index("ix_payments_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} status={self.status} "
            f"amount={self.amount} {self.currency}>"
        )

    def ai_result(self, spoken_message: str) -> dict:
        """The ONLY shape allowed to reach the LLM. No provider refs, no token."""
        return {
            "status": self.status,
            "payment_id": str(self.id),
            "message": spoken_message,
        }

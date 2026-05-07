"""Billing Models — account_billing_config and call_billing_items.

Multi-tenant isolation: call_billing_items is scoped by account_id.
account_billing_config uses account_id IS NULL for the platform default row.

Rates are append-only (new row per change). Historical items always reference
the config row that was current at call-end, so rate edits never mutate past cost.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from botelier.database import Base


class AccountBillingConfig(Base):
    """Per-account billing rate config (append-only).

    The active rate for an account is the row with the latest effective_from
    that is <= now(). A platform default row exists with account_id = NULL.

    last_threshold_alert_at — records the most recent time a billing threshold
    crossing email was dispatched for this account. Compared against the current
    calendar month so each crossing fires at most once per month.
    """

    __tablename__ = "account_billing_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    inbound_rate_usd = Column(Numeric(10, 6), nullable=False, default=0.05)
    outbound_rate_usd = Column(Numeric(10, 6), nullable=False, default=0.08)
    sms_inbound_rate_usd = Column(Numeric(10, 6), nullable=False, default=0.01)
    sms_outbound_rate_usd = Column(Numeric(10, 6), nullable=False, default=0.01)

    monthly_alert_threshold_usd = Column(Numeric(10, 2), nullable=True)

    # NOTE: last_threshold_alert_at is retained for schema compatibility but is
    # NOT used for deduplication.  The authoritative dedup source is the
    # account_billing_alerts table (unique on account_id + alert_year +
    # alert_month), which gives per-account isolation and atomic race safety.
    last_threshold_alert_at = Column(DateTime, nullable=True)

    effective_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        label = str(self.account_id) if self.account_id else "PLATFORM_DEFAULT"
        return f"<AccountBillingConfig {label} from={self.effective_from}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "account_id": str(self.account_id) if self.account_id else None,
            "inbound_rate_usd": float(self.inbound_rate_usd),
            "outbound_rate_usd": float(self.outbound_rate_usd),
            "sms_inbound_rate_usd": float(self.sms_inbound_rate_usd),
            "sms_outbound_rate_usd": float(self.sms_outbound_rate_usd),
            "monthly_alert_threshold_usd": float(self.monthly_alert_threshold_usd)
            if self.monthly_alert_threshold_usd is not None
            else None,
            "last_threshold_alert_at": self.last_threshold_alert_at.isoformat() + "Z"
            if self.last_threshold_alert_at
            else None,
            "effective_from": self.effective_from.isoformat() + "Z"
            if self.effective_from
            else None,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }


class AccountBillingAlert(Base):
    """Per-account, per-calendar-month billing threshold alert record.

    One row is inserted (atomically, ON CONFLICT DO NOTHING) the first time an
    account's MTD spend crosses its configured alert threshold in a given month.
    The unique constraint on (account_id, alert_year, alert_month) makes the
    INSERT the race-safe deduplication primitive — no two workers can both claim
    the slot. The row is only committed after confirmed email delivery, so a
    failed send leaves no row and the next call completion can retry.
    """

    __tablename__ = "account_billing_alerts"
    __table_args__ = (
        UniqueConstraint("account_id", "alert_year", "alert_month", name="uq_billing_alert_account_month"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    alert_year = Column(Integer, nullable=False)
    alert_month = Column(Integer, nullable=False)
    alerted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    spend_usd = Column(Numeric(10, 4), nullable=True)
    threshold_usd = Column(Numeric(10, 4), nullable=True)

    account = relationship("Account", foreign_keys=[account_id])

    def __repr__(self):
        return f"<AccountBillingAlert account={self.account_id} {self.alert_year}-{self.alert_month:02d}>"


class CallBillingItem(Base):
    """Immutable billing line item written at call-end.

    item_type:
      'inbound_call'       — one row per completed call (full call duration).
      'outbound_transfer'  — one row per transfer leg.

    quantity_minutes = ceil(duration_seconds / 60).
    cost_usd = quantity_minutes * rate_per_unit_usd (frozen at call-end).
    """

    __tablename__ = "call_billing_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    call_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=False,
        index=True,
    )

    item_type = Column(String(32), nullable=False)

    quantity_minutes = Column(Integer, nullable=False, default=0)
    rate_per_unit_usd = Column(Numeric(10, 6), nullable=False)
    cost_usd = Column(Numeric(10, 6), nullable=False)

    billing_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("account_billing_config.id"),
        nullable=True,
    )

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    call_log = relationship("CallLog", foreign_keys=[call_log_id])
    billing_config = relationship("AccountBillingConfig", foreign_keys=[billing_config_id])

    def __repr__(self):
        return f"<CallBillingItem {self.item_type} {self.cost_usd} USD>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "call_log_id": str(self.call_log_id),
            "account_id": str(self.account_id),
            "item_type": self.item_type,
            "quantity_minutes": self.quantity_minutes,
            "rate_per_unit_usd": float(self.rate_per_unit_usd),
            "cost_usd": float(self.cost_usd),
            "billing_config_id": str(self.billing_config_id) if self.billing_config_id else None,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }

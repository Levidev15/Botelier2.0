"""Canonical call-duration and voice-billing finalization.

Provider durations and Pipecat media durations are separate facts:

* The parent Twilio call owns total inbound duration and inbound billing.
* A child Twilio call owns one warm-transfer leg and outbound billing.
* Pipecat owns the AI/media leg duration and never creates voice billing.

Methods mutate the supplied SQLAlchemy session but never commit it.
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from botelier.models.billing import AccountBillingConfig, CallBillingItem
from botelier.models.call_log import CallLeg, CallLog


class CallDurationBillingService:
    """Apply canonical duration facts and their matching billing line items."""

    DEFAULT_INBOUND_RATE = Decimal("0.05")
    DEFAULT_OUTBOUND_RATE = Decimal("0.03")

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalized_duration(duration_seconds: int) -> int:
        return max(0, int(duration_seconds))

    def get_effective_config(self, account_id) -> Optional[AccountBillingConfig]:
        now = datetime.utcnow()
        config = (
            self.db.query(AccountBillingConfig)
            .filter(
                AccountBillingConfig.account_id == account_id,
                AccountBillingConfig.effective_from <= now,
            )
            .order_by(AccountBillingConfig.effective_from.desc())
            .first()
        )
        if config is not None:
            return config
        return (
            self.db.query(AccountBillingConfig)
            .filter(
                AccountBillingConfig.account_id.is_(None),
                AccountBillingConfig.effective_from <= now,
            )
            .order_by(AccountBillingConfig.effective_from.desc())
            .first()
        )

    def finalize_parent(
        self,
        call_log: CallLog,
        duration_seconds: int,
        *,
        source: str,
        rate: Optional[Decimal] = None,
        billing_config_id=None,
    ) -> CallBillingItem:
        """Persist authoritative parent duration and its inbound line item."""
        duration = self._normalized_duration(duration_seconds)
        call_log.duration_seconds = duration
        call_log.duration_source = source
        item = self.upsert_inbound_billing(
            call_log,
            duration,
            source=source,
            rate=rate,
            billing_config_id=billing_config_id,
        )
        self.recompute_estimated_cost(call_log)
        return item

    def finalize_ai_leg(
        self,
        leg: CallLeg,
        duration_seconds: int,
        *,
        source: str = "pipecat",
    ) -> None:
        """Persist Pipecat's AI/media duration without changing voice billing."""
        leg.duration_seconds = self._normalized_duration(duration_seconds)
        leg.duration_source = source

    def finalize_transfer_leg(
        self,
        call_log: CallLog,
        leg: CallLeg,
        duration_seconds: int,
        *,
        source: str,
        rate: Optional[Decimal] = None,
        billing_config_id=None,
    ) -> CallBillingItem:
        """Persist authoritative child-call duration and its outbound line item."""
        duration = self._normalized_duration(duration_seconds)
        leg.duration_seconds = duration
        leg.duration_source = source
        item = self.upsert_transfer_billing(
            call_log,
            leg,
            duration,
            source=source,
            rate=rate,
            billing_config_id=billing_config_id,
        )
        self.recompute_estimated_cost(call_log)
        return item

    def upsert_inbound_billing(
        self,
        call_log: CallLog,
        duration_seconds: int,
        *,
        source: str,
        rate: Optional[Decimal] = None,
        billing_config_id=None,
    ) -> CallBillingItem:
        duration = self._normalized_duration(duration_seconds)
        item = (
            self.db.query(CallBillingItem)
            .filter(
                CallBillingItem.call_log_id == call_log.id,
                CallBillingItem.item_type == "inbound_call",
            )
            .first()
        )
        config = None
        if item is None and rate is None:
            config = self.get_effective_config(call_log.account_id)
        resolved_rate = Decimal(
            str(
                rate
                if rate is not None
                else (
                    config.inbound_rate_usd
                    if config is not None
                    else self.DEFAULT_INBOUND_RATE
                )
            )
        )
        if item is not None and rate is None:
            resolved_rate = Decimal(str(item.rate_per_unit_usd))
        resolved_config_id = (
            billing_config_id
            if billing_config_id is not None
            else (
                item.billing_config_id
                if item is not None
                else (config.id if config is not None else None)
            )
        )
        minutes = math.ceil(duration / 60) if duration > 0 else 0
        cost = Decimal(minutes) * resolved_rate

        if item is None:
            item = CallBillingItem(
                call_log_id=call_log.id,
                account_id=call_log.account_id,
                item_type="inbound_call",
            )
            self.db.add(item)

        item.call_leg_id = None
        item.source_duration_seconds = duration
        item.duration_source = source
        item.quantity_minutes = minutes
        item.rate_per_unit_usd = resolved_rate
        item.cost_usd = cost
        item.billing_config_id = resolved_config_id
        return item

    def upsert_transfer_billing(
        self,
        call_log: CallLog,
        leg: CallLeg,
        duration_seconds: int,
        *,
        source: str,
        rate: Optional[Decimal] = None,
        billing_config_id=None,
    ) -> CallBillingItem:
        duration = self._normalized_duration(duration_seconds)
        if leg.id is None:
            self.db.flush()
        item = (
            self.db.query(CallBillingItem)
            .filter(
                CallBillingItem.call_leg_id == leg.id,
                CallBillingItem.item_type == "outbound_transfer",
            )
            .first()
        )
        config = None
        if item is None and rate is None:
            config = self.get_effective_config(call_log.account_id)
        resolved_rate = Decimal(
            str(
                rate
                if rate is not None
                else (
                    config.outbound_rate_usd
                    if config is not None
                    else self.DEFAULT_OUTBOUND_RATE
                )
            )
        )
        if item is not None and rate is None:
            resolved_rate = Decimal(str(item.rate_per_unit_usd))
        resolved_config_id = (
            billing_config_id
            if billing_config_id is not None
            else (
                item.billing_config_id
                if item is not None
                else (config.id if config is not None else None)
            )
        )
        minutes = math.ceil(duration / 60) if duration > 0 else 0
        cost = Decimal(minutes) * resolved_rate

        if item is None:
            item = CallBillingItem(
                call_log_id=call_log.id,
                call_leg_id=leg.id,
                account_id=call_log.account_id,
                item_type="outbound_transfer",
            )
            self.db.add(item)

        item.call_leg_id = leg.id
        item.source_duration_seconds = duration
        item.duration_source = source
        item.quantity_minutes = minutes
        item.rate_per_unit_usd = resolved_rate
        item.cost_usd = cost
        item.billing_config_id = resolved_config_id
        return item

    def recompute_estimated_cost(self, call_log: CallLog) -> Decimal:
        self.db.flush()
        total = (
            self.db.query(func.coalesce(func.sum(CallBillingItem.cost_usd), 0))
            .filter(CallBillingItem.call_log_id == call_log.id)
            .scalar()
        )
        resolved = Decimal(str(total or 0))
        call_log.estimated_cost_usd = resolved
        return resolved

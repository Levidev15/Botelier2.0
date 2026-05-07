"""Billing Alert Service — threshold crossing detection and notification.

Checks whether a given account has exceeded its monthly billing threshold.
When the threshold is first crossed in a calendar month an email is dispatched
to all active platform admins and the account owner.

Deduplication and race-safety
------------------------------
Duplicate suppression is handled by a dedicated ``account_billing_alerts``
table with a UNIQUE constraint on ``(account_id, alert_year, alert_month)``.
An atomic ``INSERT … ON CONFLICT DO NOTHING`` is used to "claim" the alert
slot.  Two concurrent background tasks that both observe an uncrossed threshold
will race to insert — exactly one will see ``rowcount == 1`` and proceed to
send email; the other sees ``rowcount == 0`` and silently exits.

Importantly, the insert is committed **only after** email delivery succeeds.
If the SMTP call fails the transaction is rolled back, the alert row is not
persisted, and the next call completion for the same account can retry.

Isolation contract
------------------
This service opens its own short-lived database session (via SessionLocal) and
commits nothing when the threshold has not been crossed or when email delivery
fails.  A failure here never rolls back the call log or billing items that were
already committed.

Entry points
------------
``check_billing_threshold(account_id)``
    Synchronous helper suitable for use in FastAPI BackgroundTasks threads.

``run_billing_alert_background(account_id)``
    Thin wrapper that catches all exceptions so the background task machinery
    never sees an unhandled error.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from botelier.models.account import Account
from botelier.models.billing import AccountBillingAlert, AccountBillingConfig, CallBillingItem
from botelier.models.call_log import CallLog
from botelier.models.sms_conversation import MessageDirection, SMSConversation, SMSMessage
from botelier.models.user import User, UserType
from botelier.services.email_service import send_email

_DEFAULT_SMS_IN_RATE = 0.01
_DEFAULT_SMS_OUT_RATE = 0.01


def _get_effective_config(db: Session, account_id) -> Optional[AccountBillingConfig]:
    """Return the most recent billing config for the account (or platform default).

    Used *only* to read rate values and the alert threshold.  Never used to
    write deduplication state — that belongs in ``account_billing_alerts``.
    """
    now = datetime.utcnow()
    config = (
        db.query(AccountBillingConfig)
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
        db.query(AccountBillingConfig)
        .filter(
            AccountBillingConfig.account_id.is_(None),
            AccountBillingConfig.effective_from <= now,
        )
        .order_by(AccountBillingConfig.effective_from.desc())
        .first()
    )


def _compute_mtd_spend(db: Session, account_id) -> float:
    """Return the total MTD spend in USD for the account (calls + SMS)."""
    now = datetime.utcnow()
    mtd_start = datetime(now.year, now.month, 1)

    call_cost = (
        db.query(func.coalesce(func.sum(CallBillingItem.cost_usd), 0))
        .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
        .filter(
            CallBillingItem.account_id == account_id,
            CallLog.started_at >= mtd_start,
        )
        .scalar()
    )
    call_cost = float(call_cost or 0)

    config = _get_effective_config(db, account_id)
    sms_in_rate = float(config.sms_inbound_rate_usd) if config else _DEFAULT_SMS_IN_RATE
    sms_out_rate = float(config.sms_outbound_rate_usd) if config else _DEFAULT_SMS_OUT_RATE

    conv_subq = (
        db.query(SMSConversation.id)
        .filter(SMSConversation.account_id == account_id)
        .subquery()
    )
    sms_in_count = (
        db.query(func.count(SMSMessage.id))
        .filter(
            SMSMessage.conversation_id.in_(conv_subq),
            SMSMessage.direction == MessageDirection.INBOUND.value,
            SMSMessage.created_at >= mtd_start,
        )
        .scalar()
        or 0
    )
    sms_out_count = (
        db.query(func.count(SMSMessage.id))
        .filter(
            SMSMessage.conversation_id.in_(conv_subq),
            SMSMessage.direction == MessageDirection.OUTBOUND.value,
            SMSMessage.created_at >= mtd_start,
        )
        .scalar()
        or 0
    )
    sms_cost = sms_in_count * sms_in_rate + sms_out_count * sms_out_rate

    return round(call_cost + sms_cost, 6)


def _already_alerted_this_month(db: Session, account_id, year: int, month: int) -> bool:
    """Fast read-only check — True if a committed alert row exists for this month.

    This is a non-atomic fast-path to avoid spinning up an SMTP connection on
    the hot path.  The actual race-safe deduplication happens in
    ``_try_claim_alert_slot``.
    """
    return (
        db.query(AccountBillingAlert)
        .filter(
            AccountBillingAlert.account_id == account_id,
            AccountBillingAlert.alert_year == year,
            AccountBillingAlert.alert_month == month,
        )
        .count()
        > 0
    )


def _try_claim_alert_slot(
    db: Session,
    account_id,
    year: int,
    month: int,
    spend_usd: float,
    threshold_usd: float,
) -> bool:
    """Atomically INSERT a billing alert row for this account+month.

    Returns True if this worker successfully claimed the slot (rowcount == 1),
    False if another worker already claimed it (ON CONFLICT DO NOTHING fired,
    rowcount == 0).

    The insert is flushed to the DB but **not committed** — the caller must
    call ``db.commit()`` on success or ``db.rollback()`` on failure so that an
    email delivery error leaves no residual row, enabling future retries.
    """
    new_id = str(uuid.uuid4())
    now = datetime.utcnow()
    result = db.execute(
        text(
            """
            INSERT INTO account_billing_alerts
                (id, account_id, alert_year, alert_month, alerted_at, spend_usd, threshold_usd)
            VALUES
                (:id, :account_id, :year, :month, :now, :spend, :threshold)
            ON CONFLICT (account_id, alert_year, alert_month) DO NOTHING
            """
        ),
        {
            "id": new_id,
            "account_id": str(account_id),
            "year": year,
            "month": month,
            "now": now,
            "spend": round(spend_usd, 4),
            "threshold": round(threshold_usd, 4),
        },
    )
    return result.rowcount == 1


def _send_threshold_alert(
    db: Session,
    account: Account,
    mtd_spend: float,
    threshold: float,
) -> bool:
    """Dispatch the threshold alert email to platform admins and the account owner.

    Returns True if at least one email was accepted by the SMTP server,
    False if delivery was skipped (no recipients, SMTP unconfigured) or failed.
    """
    now = datetime.utcnow()
    month_label = now.strftime("%B %Y")

    admin_emails = [
        row.email
        for row in db.query(User.email)
        .filter(User.user_type == UserType.PLATFORM_ADMIN, User.is_active.is_(True))
        .all()
    ]

    recipient_emails = list(set(admin_emails))
    if account.email and account.email not in recipient_emails:
        recipient_emails.append(account.email)

    if not recipient_emails:
        logger.warning(
            f"billing_alert: no recipients found for account {account.id} — skipping email"
        )
        return False

    subject = f"[Botelier] Billing threshold exceeded — {account.name} ({month_label})"

    body_text = (
        f"Billing Alert — {month_label}\n"
        f"{'=' * 50}\n\n"
        f"Account:    {account.name}\n"
        f"Account ID: {account.id}\n\n"
        f"The month-to-date spend for this account has crossed the configured\n"
        f"alert threshold.\n\n"
        f"  MTD Spend:  ${mtd_spend:,.2f}\n"
        f"  Threshold:  ${threshold:,.2f}\n\n"
        f"You are receiving this message because you are a platform administrator\n"
        f"or the account owner. This alert fires at most once per calendar month.\n\n"
        f"Log in to the Botelier admin panel to review usage details.\n"
    )

    body_html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;color:#1a1a1a;max-width:600px;margin:0 auto;padding:20px;">
  <h2 style="color:#dc2626;">Billing Threshold Exceeded</h2>
  <p style="color:#6b7280;">{month_label}</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0;">
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-weight:600;background:#f9fafb;width:40%;">Account</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;">{account.name}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-weight:600;background:#f9fafb;">Account ID</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-family:monospace;font-size:13px;">{account.id}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-weight:600;background:#f9fafb;">MTD Spend</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#dc2626;font-weight:600;">${mtd_spend:,.2f}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-weight:600;background:#f9fafb;">Alert Threshold</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;">${threshold:,.2f}</td>
    </tr>
  </table>
  <p style="font-size:14px;color:#6b7280;">
    This alert fires at most once per calendar month. Log in to the Botelier
    admin panel to review detailed usage for this account.
  </p>
</body>
</html>"""

    success = send_email(
        to_addresses=recipient_emails,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )

    if success:
        logger.info(
            f"billing_alert: threshold alert sent for account {account.id} ({account.name}) "
            f"— spend={mtd_spend:.2f} threshold={threshold:.2f} recipients={recipient_emails}"
        )
    else:
        logger.warning(
            f"billing_alert: email delivery failed for account {account.id} ({account.name}) "
            f"— spend={mtd_spend:.2f} threshold={threshold:.2f}"
        )

    return success


def check_billing_threshold(account_id) -> None:
    """Check MTD spend against the alert threshold and send email if newly crossed.

    Opens its own DB session so this can safely run in a background thread
    without sharing the request session.

    Deduplication is atomic and per-account — it never touches the shared
    platform-default billing config row.  Two concurrent calls for the same
    account+month will race on an INSERT ON CONFLICT DO NOTHING; exactly one
    will proceed to send email.  The alert row is committed only after
    confirmed SMTP delivery; a failed send rolls the insert back, allowing the
    next call completion to retry.

    Args:
        account_id: UUID (or str) of the account to check.
    """
    from botelier.database import SessionLocal

    db: Session = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            logger.warning(f"billing_alert: account {account_id} not found, skipping")
            return

        config = _get_effective_config(db, account_id)
        if config is None or config.monthly_alert_threshold_usd is None:
            return

        threshold = float(config.monthly_alert_threshold_usd)
        if threshold <= 0:
            return

        now = datetime.utcnow()
        year, month = now.year, now.month

        if _already_alerted_this_month(db, account_id, year, month):
            logger.debug(
                f"billing_alert: already alerted this month for account {account_id}, skipping"
            )
            return

        mtd_spend = _compute_mtd_spend(db, account_id)

        if mtd_spend < threshold:
            return

        logger.info(
            f"billing_alert: threshold crossed for account {account_id} "
            f"— spend={mtd_spend:.2f} threshold={threshold:.2f}"
        )

        claimed = _try_claim_alert_slot(db, account_id, year, month, mtd_spend, threshold)
        if not claimed:
            logger.debug(
                f"billing_alert: another worker already claimed the alert slot for "
                f"account {account_id} {year}-{month:02d} — skipping"
            )
            return

        delivered = _send_threshold_alert(db, account, mtd_spend, threshold)

        if delivered:
            db.commit()
            logger.info(
                f"billing_alert: alert row committed for account {account_id} {year}-{month:02d}"
            )
        else:
            db.rollback()
            logger.warning(
                f"billing_alert: email delivery failed — alert row rolled back for "
                f"account {account_id} {year}-{month:02d}; will retry on next call completion"
            )

    except Exception:
        logger.exception(
            f"billing_alert: unexpected error checking threshold for account {account_id}"
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def run_billing_alert_background(account_id) -> None:
    """Top-level background task entry point — never raises.

    Wraps :func:`check_billing_threshold` with a catch-all exception guard so
    FastAPI's background task machinery never sees an unhandled error from this
    service.
    """
    try:
        check_billing_threshold(account_id)
    except Exception:
        logger.exception(
            f"billing_alert: run_billing_alert_background failed for account {account_id}"
        )

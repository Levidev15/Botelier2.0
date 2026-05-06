"""Account Billing API — usage summary, call list, timeseries, and rate config.

All routes are scoped to the authenticated account and require usage.view permission.
The CSV export on /usage/calls requires usage.export.

Period shorthand: 7d | 30d | mtd | custom (requires ?from=&to=).
"""

import csv
import io
from datetime import datetime, timedelta
from math import ceil
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.assistant import Assistant
from botelier.models.billing import AccountBillingConfig, CallBillingItem
from botelier.models.call_log import CallLog, CallLeg
from botelier.models.sms_conversation import MessageDirection, SMSConversation, SMSMessage
from botelier.models.user import User

router = APIRouter(prefix="/api/billing", tags=["Billing"])

_DEFAULT_INBOUND_RATE = 0.05
_DEFAULT_OUTBOUND_RATE = 0.08
_DEFAULT_SMS_IN_RATE = 0.01
_DEFAULT_SMS_OUT_RATE = 0.01


def _resolve_period(
    period: str,
    from_: Optional[datetime],
    to_: Optional[datetime],
) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for the requested period shorthand."""
    now = datetime.utcnow()
    if period == "7d":
        return now - timedelta(days=7), now
    if period == "30d":
        return now - timedelta(days=30), now
    if period == "mtd":
        return datetime(now.year, now.month, 1), now
    if period == "custom":
        if not from_ or not to_:
            raise HTTPException(
                status_code=400,
                detail="period=custom requires both ?from= and ?to= query parameters",
            )
        if to_ < from_:
            raise HTTPException(status_code=400, detail="?to must be >= ?from")
        return from_, to_
    # Unknown shorthand — default to 30 days
    return now - timedelta(days=30), now


def _get_effective_config(db: Session, account_id) -> Optional[AccountBillingConfig]:
    """Return the most recent config for the account, falling back to the platform default."""
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


def _config_rates(config: Optional[AccountBillingConfig]) -> dict:
    if config is None:
        return {
            "inbound": _DEFAULT_INBOUND_RATE,
            "outbound": _DEFAULT_OUTBOUND_RATE,
            "sms_in": _DEFAULT_SMS_IN_RATE,
            "sms_out": _DEFAULT_SMS_OUT_RATE,
        }
    return {
        "inbound": float(config.inbound_rate_usd),
        "outbound": float(config.outbound_rate_usd),
        "sms_in": float(config.sms_inbound_rate_usd),
        "sms_out": float(config.sms_outbound_rate_usd),
    }


def _sms_conv_subq(db: Session, account_id):
    return db.query(SMSConversation.id).filter(SMSConversation.account_id == account_id).subquery()


@router.get("/usage/summary")
async def get_usage_summary(
    account_id: UUID = Query(..., description="Account UUID"),
    period: str = Query("30d", description="Period shorthand: 7d | 30d | mtd | custom"),
    from_: Optional[datetime] = Query(None, alias="from", description="Start (ISO 8601), required when period=custom"),
    to_: Optional[datetime] = Query(None, alias="to", description="End (ISO 8601), required when period=custom"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Usage summary for the account: inbound/outbound minutes, SMS counts, and costs."""
    check_account_permission(user, str(account_id), "usage.view", db)
    try:
        period_start, period_end = _resolve_period(period, from_, to_)

        inbound_row = (
            db.query(
                func.count(CallBillingItem.id).label("call_count"),
                func.coalesce(func.sum(CallBillingItem.quantity_minutes), 0).label("total_minutes"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("total_cost"),
            )
            .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.account_id == account_id,
                CallBillingItem.item_type == "inbound_call",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .one()
        )

        outbound_row = (
            db.query(
                func.count(CallBillingItem.id).label("transfer_count"),
                func.coalesce(func.sum(CallBillingItem.quantity_minutes), 0).label("total_minutes"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("total_cost"),
            )
            .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.account_id == account_id,
                CallBillingItem.item_type == "outbound_transfer",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .one()
        )

        config = _get_effective_config(db, account_id)
        rates = _config_rates(config)

        conv_subq = _sms_conv_subq(db, account_id)
        sms_in_count = (
            db.query(func.count(SMSMessage.id))
            .filter(
                SMSMessage.conversation_id.in_(conv_subq),
                SMSMessage.direction == MessageDirection.INBOUND.value,
                SMSMessage.created_at >= period_start,
                SMSMessage.created_at <= period_end,
            )
            .scalar()
            or 0
        )
        sms_out_count = (
            db.query(func.count(SMSMessage.id))
            .filter(
                SMSMessage.conversation_id.in_(conv_subq),
                SMSMessage.direction == MessageDirection.OUTBOUND.value,
                SMSMessage.created_at >= period_start,
                SMSMessage.created_at <= period_end,
            )
            .scalar()
            or 0
        )

        inbound_cost = float(inbound_row.total_cost)
        outbound_cost = float(outbound_row.total_cost)
        sms_cost = round(sms_in_count * rates["sms_in"] + sms_out_count * rates["sms_out"], 6)
        total_cost = round(inbound_cost + outbound_cost + sms_cost, 6)

        return {
            "period_start": period_start.isoformat() + "Z",
            "period_end": period_end.isoformat() + "Z",
            "inbound_calls": int(inbound_row.call_count),
            "inbound_minutes": int(inbound_row.total_minutes),
            "inbound_cost_usd": round(inbound_cost, 6),
            "outbound_transfers": int(outbound_row.transfer_count),
            "outbound_minutes": int(outbound_row.total_minutes),
            "outbound_cost_usd": round(outbound_cost, 6),
            "sms_inbound_count": sms_in_count,
            "sms_outbound_count": sms_out_count,
            "sms_cost_usd": sms_cost,
            "total_cost_usd": total_cost,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching billing summary for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch usage summary")


@router.get("/usage/calls")
async def get_usage_calls(
    account_id: UUID = Query(..., description="Account UUID"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    format: Optional[str] = Query(None, description="Set to 'csv' to stream all rows without pagination (requires usage.export)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Paginated call list with billing items embedded per row.

    Set ?format=csv to download all rows as CSV (requires usage.export permission).
    """
    check_account_permission(user, str(account_id), "usage.view", db)
    if format == "csv":
        check_account_permission(user, str(account_id), "usage.export", db)

    try:
        now = datetime.utcnow()
        date_from = from_ or (now - timedelta(days=30))
        date_to = to_ or now

        base_q = (
            db.query(CallLog)
            .filter(
                CallLog.account_id == account_id,
                CallLog.started_at >= date_from,
                CallLog.started_at <= date_to,
            )
            .order_by(CallLog.started_at.desc())
        )

        if format == "csv":
            call_logs = base_q.options(joinedload(CallLog.legs)).all()
        else:
            total = base_q.count()
            call_logs = (
                base_q
                .options(joinedload(CallLog.legs))
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

        # Bulk-load billing items for all fetched call_log_ids
        call_ids = [log.id for log in call_logs]
        items_by_call: dict = {}
        if call_ids:
            billing_items = (
                db.query(CallBillingItem)
                .filter(CallBillingItem.call_log_id.in_(call_ids))
                .all()
            )
            for item in billing_items:
                items_by_call.setdefault(str(item.call_log_id), []).append(item)

        # Bulk-load assistant names
        asst_ids = {log.assistant_id for log in call_logs if log.assistant_id}
        asst_names: dict = {}
        if asst_ids:
            for a in db.query(Assistant).filter(Assistant.id.in_(asst_ids)):
                asst_names[str(a.id)] = a.name

        def _build_row(log: CallLog) -> dict:
            items = items_by_call.get(str(log.id), [])
            inbound_item = next((i for i in items if i.item_type == "inbound_call"), None)
            inbound_minutes = inbound_item.quantity_minutes if inbound_item else (
                ceil(log.duration_seconds / 60) if log.duration_seconds else 0
            )
            inbound_cost = float(inbound_item.cost_usd) if inbound_item else 0.0
            total_cost = sum(float(i.cost_usd) for i in items)
            return {
                "call_log_id": str(log.id),
                "reference_id": log.reference_id,
                "started_at": log.started_at.isoformat() + "Z" if log.started_at else None,
                "direction": getattr(log, "direction", "inbound") or "inbound",
                "caller_number": log.caller_number,
                "to_number": log.to_number,
                "assistant_name": asst_names.get(str(log.assistant_id)) if log.assistant_id else None,
                "duration_seconds": log.duration_seconds or 0,
                "billable_inbound_minutes": inbound_minutes,
                "inbound_cost_usd": round(inbound_cost, 6),
                "has_transfers": bool(log.has_transfer),
                "total_cost_usd": round(total_cost, 6),
                "billing_items": [i.to_dict() for i in items],
            }

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Reference ID", "Started At", "Direction", "Caller", "To Number",
                "Assistant", "Duration (s)", "Billable Inbound Minutes",
                "Inbound Cost (USD)", "Has Transfers", "Total Cost (USD)",
            ])
            for log in call_logs:
                row = _build_row(log)
                writer.writerow([
                    row["reference_id"] or "",
                    row["started_at"] or "",
                    row["direction"],
                    row["caller_number"] or "",
                    row["to_number"] or "",
                    row["assistant_name"] or "",
                    row["duration_seconds"],
                    row["billable_inbound_minutes"],
                    row["inbound_cost_usd"],
                    "Yes" if row["has_transfers"] else "No",
                    row["total_cost_usd"],
                ])
            output.seek(0)
            filename = f"billing_calls_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        rows = [_build_row(log) for log in call_logs]
        return {
            "calls": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "period_start": date_from.isoformat() + "Z",
            "period_end": date_to.isoformat() + "Z",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching billing calls for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch billing calls")


@router.get("/usage/timeseries")
async def get_usage_timeseries(
    account_id: UUID = Query(..., description="Account UUID"),
    period: str = Query("30d", description="Period shorthand: 7d | 30d | mtd | custom"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
    bucket: str = Query("day", description="Aggregation bucket: day | week"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Daily or weekly cost timeseries split by inbound, outbound, and SMS."""
    check_account_permission(user, str(account_id), "usage.view", db)
    if bucket not in ("day", "week"):
        raise HTTPException(status_code=400, detail="bucket must be 'day' or 'week'")
    try:
        period_start, period_end = _resolve_period(period, from_, to_)

        trunc = func.date_trunc(bucket, CallLog.started_at)

        inbound_rows = (
            db.query(
                trunc.label("bucket"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("cost"),
            )
            .join(CallBillingItem, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.account_id == account_id,
                CallBillingItem.item_type == "inbound_call",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .group_by("bucket")
            .order_by("bucket")
            .all()
        )

        outbound_rows = (
            db.query(
                trunc.label("bucket"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("cost"),
            )
            .join(CallBillingItem, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.account_id == account_id,
                CallBillingItem.item_type == "outbound_transfer",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .group_by("bucket")
            .order_by("bucket")
            .all()
        )

        config = _get_effective_config(db, account_id)
        rates = _config_rates(config)
        conv_subq = _sms_conv_subq(db, account_id)

        sms_trunc = func.date_trunc(bucket, SMSMessage.created_at)
        sms_rows = (
            db.query(
                sms_trunc.label("bucket"),
                SMSMessage.direction,
                func.count(SMSMessage.id).label("cnt"),
            )
            .filter(
                SMSMessage.conversation_id.in_(conv_subq),
                SMSMessage.created_at >= period_start,
                SMSMessage.created_at <= period_end,
            )
            .group_by("bucket", SMSMessage.direction)
            .order_by("bucket")
            .all()
        )

        # Build merged map keyed by bucket date string
        inbound_map = {r.bucket.date().isoformat(): float(r.cost) for r in inbound_rows}
        outbound_map = {r.bucket.date().isoformat(): float(r.cost) for r in outbound_rows}

        sms_in_map: dict = {}
        sms_out_map: dict = {}
        for r in sms_rows:
            key = r.bucket.date().isoformat()
            if r.direction == MessageDirection.INBOUND.value:
                sms_in_map[key] = sms_in_map.get(key, 0) + int(r.cnt)
            else:
                sms_out_map[key] = sms_out_map.get(key, 0) + int(r.cnt)

        all_keys = sorted(
            set(inbound_map) | set(outbound_map) | set(sms_in_map) | set(sms_out_map)
        )

        timeseries = []
        for key in all_keys:
            in_cost = inbound_map.get(key, 0.0)
            out_cost = outbound_map.get(key, 0.0)
            sms_cost = round(
                sms_in_map.get(key, 0) * rates["sms_in"]
                + sms_out_map.get(key, 0) * rates["sms_out"],
                6,
            )
            timeseries.append({
                "date": key,
                "inbound_cost_usd": round(in_cost, 6),
                "outbound_cost_usd": round(out_cost, 6),
                "sms_cost_usd": sms_cost,
                "total_cost_usd": round(in_cost + out_cost + sms_cost, 6),
            })

        return {
            "period_start": period_start.isoformat() + "Z",
            "period_end": period_end.isoformat() + "Z",
            "bucket": bucket,
            "timeseries": timeseries,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching billing timeseries for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch billing timeseries")


@router.get("/config")
async def get_billing_config(
    account_id: UUID = Query(..., description="Account UUID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the account's current effective billing rates (read-only)."""
    check_account_permission(user, str(account_id), "usage.view", db)
    try:
        config = _get_effective_config(db, account_id)
        rates = _config_rates(config)
        return {
            "account_id": str(account_id),
            "inbound_rate_usd": rates["inbound"],
            "outbound_rate_usd": rates["outbound"],
            "sms_inbound_rate_usd": rates["sms_in"],
            "sms_outbound_rate_usd": rates["sms_out"],
            "monthly_alert_threshold_usd": (
                float(config.monthly_alert_threshold_usd)
                if config and config.monthly_alert_threshold_usd is not None
                else None
            ),
            "effective_from": (
                config.effective_from.isoformat() + "Z"
                if config and config.effective_from
                else None
            ),
            "is_platform_default": config is None or config.account_id is None,
        }
    except Exception as e:
        logger.exception(f"Error fetching billing config for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch billing config")

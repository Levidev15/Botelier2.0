"""Admin Billing API — cross-account usage table, per-account detail, and rate config.

All routes require user_type == platform_admin.
Internal cost columns (LLM, TTS, STT) are never exposed on account-facing routes.

Admin-only platform rates used for internal cost-of-goods calculation.
These are not the per-account billing rates charged to customers.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from botelier.auth.middleware import get_platform_admin
from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.assistant import Assistant
from botelier.models.billing import AccountBillingConfig, CallBillingItem
from botelier.models.call_log import CallLog
from botelier.models.sms_conversation import MessageDirection, SMSConversation, SMSMessage
from botelier.models.user import User

router = APIRouter(prefix="/api/admin/billing", tags=["Admin — Billing"])

# Internal platform rates for cost-of-goods (never exposed to tenants)
_INTERNAL_LLM_RATE_PER_1K_PROMPT = 0.003
_INTERNAL_LLM_RATE_PER_1K_COMPLETION = 0.006
_INTERNAL_TTS_RATE_PER_1K_CHARS = 0.015
_INTERNAL_STT_RATE_PER_SECOND = 0.0001

_DEFAULT_INBOUND_RATE = 0.05
_DEFAULT_OUTBOUND_RATE = 0.08
_DEFAULT_SMS_IN_RATE = 0.01
_DEFAULT_SMS_OUT_RATE = 0.01


def _resolve_period(
    period: str,
    from_: Optional[datetime],
    to_: Optional[datetime],
) -> tuple[datetime, datetime]:
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
                detail="period=custom requires both ?from= and ?to=",
            )
        if to_ < from_:
            raise HTTPException(status_code=400, detail="?to must be >= ?from")
        return from_, to_
    return now - timedelta(days=30), now


def _get_effective_config(
    db: Session, account_id
) -> Optional[AccountBillingConfig]:
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


def _internal_cost(
    llm_prompt_tokens: int,
    llm_completion_tokens: int,
    tts_characters: int,
    stt_seconds: float,
) -> dict:
    llm_cost = (
        (llm_prompt_tokens / 1000) * _INTERNAL_LLM_RATE_PER_1K_PROMPT
        + (llm_completion_tokens / 1000) * _INTERNAL_LLM_RATE_PER_1K_COMPLETION
    )
    tts_cost = (tts_characters / 1000) * _INTERNAL_TTS_RATE_PER_1K_CHARS
    stt_cost = stt_seconds * _INTERNAL_STT_RATE_PER_SECOND
    return {
        "llm_prompt_tokens": llm_prompt_tokens,
        "llm_completion_tokens": llm_completion_tokens,
        "llm_cost_usd": round(llm_cost, 6),
        "tts_characters": tts_characters,
        "tts_cost_usd": round(tts_cost, 6),
        "stt_seconds": round(stt_seconds, 2),
        "stt_cost_usd": round(stt_cost, 6),
        "internal_cost_usd": round(llm_cost + tts_cost + stt_cost, 6),
    }


@router.get("/accounts")
async def list_account_usage(
    period: str = Query("30d", description="7d | 30d | mtd | custom"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
    sort_by: str = Query(
        "total_cost",
        description="Sort field: total_cost | inbound_mins | outbound_mins | account_name | internal_cost",
    ),
    order: str = Query("desc", description="asc | desc"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
):
    """All-accounts usage table for the period with internal cost breakdown."""
    if sort_by not in ("total_cost", "inbound_mins", "outbound_mins", "account_name", "internal_cost"):
        raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by!r}")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")

    try:
        period_start, period_end = _resolve_period(period, from_, to_)

        accounts = db.query(Account).filter(Account.id.isnot(None)).all()
        account_map = {str(a.id): a.name for a in accounts}

        inbound_agg = (
            db.query(
                CallBillingItem.account_id,
                func.coalesce(func.sum(CallBillingItem.quantity_minutes), 0).label("minutes"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("cost"),
                func.count(CallBillingItem.id).label("calls"),
            )
            .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.item_type == "inbound_call",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .group_by(CallBillingItem.account_id)
            .all()
        )
        inbound_by_acct = {
            str(r.account_id): {
                "minutes": int(r.minutes),
                "cost": float(r.cost),
                "calls": int(r.calls),
            }
            for r in inbound_agg
        }

        outbound_agg = (
            db.query(
                CallBillingItem.account_id,
                func.coalesce(func.sum(CallBillingItem.quantity_minutes), 0).label("minutes"),
                func.coalesce(func.sum(CallBillingItem.cost_usd), 0).label("cost"),
                func.count(CallBillingItem.id).label("transfers"),
            )
            .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.item_type == "outbound_transfer",
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .group_by(CallBillingItem.account_id)
            .all()
        )
        outbound_by_acct = {
            str(r.account_id): {
                "minutes": int(r.minutes),
                "cost": float(r.cost),
                "transfers": int(r.transfers),
            }
            for r in outbound_agg
        }

        # Internal token/character/second aggregates from call_logs
        internal_agg = (
            db.query(
                CallLog.account_id,
                func.coalesce(func.sum(CallLog.llm_prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(CallLog.llm_completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(CallLog.tts_characters), 0).label("tts_chars"),
                func.coalesce(func.sum(CallLog.stt_seconds), 0).label("stt_secs"),
            )
            .filter(
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .group_by(CallLog.account_id)
            .all()
        )
        internal_by_acct = {
            str(r.account_id): _internal_cost(
                int(r.prompt_tokens),
                int(r.completion_tokens),
                int(r.tts_chars),
                float(r.stt_secs),
            )
            for r in internal_agg
        }

        # SMS per account
        sms_agg = (
            db.query(
                SMSConversation.account_id,
                SMSMessage.direction,
                func.count(SMSMessage.id).label("cnt"),
            )
            .join(SMSMessage, SMSMessage.conversation_id == SMSConversation.id)
            .filter(
                SMSMessage.created_at >= period_start,
                SMSMessage.created_at <= period_end,
            )
            .group_by(SMSConversation.account_id, SMSMessage.direction)
            .all()
        )
        sms_in_by_acct: dict = {}
        sms_out_by_acct: dict = {}
        for r in sms_agg:
            key = str(r.account_id)
            if r.direction == MessageDirection.INBOUND.value:
                sms_in_by_acct[key] = sms_in_by_acct.get(key, 0) + int(r.cnt)
            else:
                sms_out_by_acct[key] = sms_out_by_acct.get(key, 0) + int(r.cnt)

        all_account_ids = (
            set(inbound_by_acct)
            | set(outbound_by_acct)
            | set(internal_by_acct)
            | set(sms_in_by_acct)
            | set(sms_out_by_acct)
            | set(account_map)
        )

        rows = []
        for acct_id in all_account_ids:
            config = _get_effective_config(db, acct_id)
            rates = _config_rates(config)

            inb = inbound_by_acct.get(acct_id, {"minutes": 0, "cost": 0.0, "calls": 0})
            outb = outbound_by_acct.get(acct_id, {"minutes": 0, "cost": 0.0, "transfers": 0})
            sms_in = sms_in_by_acct.get(acct_id, 0)
            sms_out = sms_out_by_acct.get(acct_id, 0)
            sms_cost = round(sms_in * rates["sms_in"] + sms_out * rates["sms_out"], 6)
            billable_total = round(inb["cost"] + outb["cost"] + sms_cost, 6)

            ic = internal_by_acct.get(acct_id, _internal_cost(0, 0, 0, 0.0))

            rows.append({
                "account_id": acct_id,
                "account_name": account_map.get(acct_id, "Unknown"),
                "inbound_calls": inb["calls"],
                "inbound_minutes": inb["minutes"],
                "inbound_cost_usd": round(inb["cost"], 6),
                "outbound_transfers": outb["transfers"],
                "outbound_minutes": outb["minutes"],
                "outbound_cost_usd": round(outb["cost"], 6),
                "sms_inbound_count": sms_in,
                "sms_outbound_count": sms_out,
                "sms_cost_usd": sms_cost,
                "billable_total_usd": billable_total,
                **ic,
                "margin_usd": round(billable_total - ic["internal_cost_usd"], 6),
            })

        reverse = order == "desc"
        if sort_by == "account_name":
            rows.sort(key=lambda r: r["account_name"].lower(), reverse=reverse)
        elif sort_by == "inbound_mins":
            rows.sort(key=lambda r: r["inbound_minutes"], reverse=reverse)
        elif sort_by == "outbound_mins":
            rows.sort(key=lambda r: r["outbound_minutes"], reverse=reverse)
        elif sort_by == "internal_cost":
            rows.sort(key=lambda r: r["internal_cost_usd"], reverse=reverse)
        else:
            rows.sort(key=lambda r: r["billable_total_usd"], reverse=reverse)

        return {
            "period_start": period_start.isoformat() + "Z",
            "period_end": period_end.isoformat() + "Z",
            "accounts": rows,
            "total_accounts": len(rows),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Admin billing accounts list error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account usage table")


@router.get("/accounts/{account_id}/detail")
async def get_account_detail(
    account_id: UUID = Path(..., description="Account UUID"),
    period: str = Query("30d"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
):
    """Full breakdown for a single account including per-call billing and MTD total."""
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        period_start, period_end = _resolve_period(period, from_, to_)

        config = _get_effective_config(db, account_id)
        rates = _config_rates(config)

        # Summary aggregates (same logic as /usage/summary)
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

        sms_cost = round(sms_in_count * rates["sms_in"] + sms_out_count * rates["sms_out"], 6)
        inbound_cost = float(inbound_row.total_cost)
        outbound_cost = float(outbound_row.total_cost)
        billable_total = round(inbound_cost + outbound_cost + sms_cost, 6)

        # Internal cost aggregates
        ic_row = (
            db.query(
                func.coalesce(func.sum(CallLog.llm_prompt_tokens), 0).label("pt"),
                func.coalesce(func.sum(CallLog.llm_completion_tokens), 0).label("ct"),
                func.coalesce(func.sum(CallLog.tts_characters), 0).label("tts"),
                func.coalesce(func.sum(CallLog.stt_seconds), 0).label("stt"),
            )
            .filter(
                CallLog.account_id == account_id,
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .one()
        )
        ic = _internal_cost(int(ic_row.pt), int(ic_row.ct), int(ic_row.tts), float(ic_row.stt))

        # MTD running total
        now = datetime.utcnow()
        mtd_start = datetime(now.year, now.month, 1)
        mtd_row = (
            db.query(func.coalesce(func.sum(CallBillingItem.cost_usd), 0))
            .join(CallLog, CallBillingItem.call_log_id == CallLog.id)
            .filter(
                CallBillingItem.account_id == account_id,
                CallLog.started_at >= mtd_start,
            )
            .scalar()
        )
        mtd_call_cost = float(mtd_row or 0)
        mtd_sms_in = (
            db.query(func.count(SMSMessage.id))
            .filter(
                SMSMessage.conversation_id.in_(conv_subq),
                SMSMessage.direction == MessageDirection.INBOUND.value,
                SMSMessage.created_at >= mtd_start,
            )
            .scalar()
            or 0
        )
        mtd_sms_out = (
            db.query(func.count(SMSMessage.id))
            .filter(
                SMSMessage.conversation_id.in_(conv_subq),
                SMSMessage.direction == MessageDirection.OUTBOUND.value,
                SMSMessage.created_at >= mtd_start,
            )
            .scalar()
            or 0
        )
        mtd_total = round(
            mtd_call_cost + mtd_sms_in * rates["sms_in"] + mtd_sms_out * rates["sms_out"], 6
        )

        # Per-call breakdown (paginated)
        call_q = (
            db.query(CallLog)
            .filter(
                CallLog.account_id == account_id,
                CallLog.started_at >= period_start,
                CallLog.started_at <= period_end,
            )
            .order_by(CallLog.started_at.desc())
        )
        total_calls = call_q.count()
        call_logs = call_q.options(joinedload(CallLog.legs)).offset((page - 1) * per_page).limit(per_page).all()

        call_ids = [log.id for log in call_logs]
        items_by_call: dict = {}
        if call_ids:
            for item in db.query(CallBillingItem).filter(CallBillingItem.call_log_id.in_(call_ids)):
                items_by_call.setdefault(str(item.call_log_id), []).append(item)

        asst_ids = {log.assistant_id for log in call_logs if log.assistant_id}
        asst_names: dict = {}
        if asst_ids:
            for a in db.query(Assistant).filter(Assistant.id.in_(asst_ids)):
                asst_names[str(a.id)] = a.name

        from math import ceil as _ceil

        def _call_row(log: CallLog) -> dict:
            items = items_by_call.get(str(log.id), [])
            inbound_item = next((i for i in items if i.item_type == "inbound_call"), None)
            inbound_mins = inbound_item.quantity_minutes if inbound_item else (
                _ceil(log.duration_seconds / 60) if log.duration_seconds else 0
            )
            inbound_c = float(inbound_item.cost_usd) if inbound_item else 0.0
            total_c = sum(float(i.cost_usd) for i in items)
            ic = _internal_cost(
                int(log.llm_prompt_tokens or 0),
                int(log.llm_completion_tokens or 0),
                int(log.tts_characters or 0),
                float(log.stt_seconds or 0),
            )
            return {
                "call_log_id": str(log.id),
                "reference_id": log.reference_id,
                "started_at": log.started_at.isoformat() + "Z" if log.started_at else None,
                "direction": getattr(log, "direction", "inbound") or "inbound",
                "caller_number": log.caller_number,
                "to_number": log.to_number,
                "assistant_name": asst_names.get(str(log.assistant_id)) if log.assistant_id else None,
                "duration_seconds": log.duration_seconds or 0,
                "billable_inbound_minutes": inbound_mins,
                "inbound_cost_usd": round(inbound_c, 6),
                "has_transfers": bool(log.has_transfer),
                "total_cost_usd": round(total_c, 6),
                "internal_cost_usd": ic["internal_cost_usd"],
                "billing_items": [i.to_dict() for i in items],
            }

        return {
            "account_id": str(account_id),
            "account_name": account.name,
            "period_start": period_start.isoformat() + "Z",
            "period_end": period_end.isoformat() + "Z",
            "summary": {
                "inbound_calls": int(inbound_row.call_count),
                "inbound_minutes": int(inbound_row.total_minutes),
                "inbound_cost_usd": round(inbound_cost, 6),
                "outbound_transfers": int(outbound_row.transfer_count),
                "outbound_minutes": int(outbound_row.total_minutes),
                "outbound_cost_usd": round(outbound_cost, 6),
                "sms_inbound_count": sms_in_count,
                "sms_outbound_count": sms_out_count,
                "sms_cost_usd": sms_cost,
                "billable_total_usd": billable_total,
                **ic,
                "margin_usd": round(billable_total - ic["internal_cost_usd"], 6),
            },
            "mtd_total_usd": mtd_total,
            "alert_threshold_usd": (
                float(config.monthly_alert_threshold_usd)
                if config and config.monthly_alert_threshold_usd is not None
                else None
            ),
            "rate_config": config.to_dict() if config else None,
            "calls": {
                "items": [_call_row(log) for log in call_logs],
                "total": total_calls,
                "page": page,
                "per_page": per_page,
                "pages": (total_calls + per_page - 1) // per_page,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Admin billing detail error for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account billing detail")


@router.get("/accounts/{account_id}/config")
async def get_account_billing_config(
    account_id: UUID = Path(..., description="Account UUID"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
):
    """Return the full config history for the account plus the currently effective row."""
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        history = (
            db.query(AccountBillingConfig)
            .filter(AccountBillingConfig.account_id == account_id)
            .order_by(AccountBillingConfig.effective_from.desc())
            .all()
        )
        platform_default = (
            db.query(AccountBillingConfig)
            .filter(
                AccountBillingConfig.account_id.is_(None),
                AccountBillingConfig.effective_from <= datetime.utcnow(),
            )
            .order_by(AccountBillingConfig.effective_from.desc())
            .first()
        )
        effective = history[0] if history else platform_default

        return {
            "account_id": str(account_id),
            "account_name": account.name,
            "effective": effective.to_dict() if effective else None,
            "is_platform_default": not bool(history),
            "history": [r.to_dict() for r in history],
            "platform_default": platform_default.to_dict() if platform_default else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Admin billing config GET error for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch billing config")


class BillingConfigUpdate(BaseModel):
    inbound_rate_usd: float
    outbound_rate_usd: float
    sms_inbound_rate_usd: float
    sms_outbound_rate_usd: float
    monthly_alert_threshold_usd: Optional[float] = None


@router.put("/accounts/{account_id}/config")
async def update_account_billing_config(
    account_id: UUID = Path(..., description="Account UUID"),
    body: BillingConfigUpdate = ...,
    db: Session = Depends(get_db),
    admin: User = Depends(get_platform_admin),
):
    """Append a new rate config row for the account (never mutates historical rows).

    The new row becomes effective immediately (effective_from = now).
    Requires billing_rates.manage — enforced by platform_admin gate.
    """
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        for field, val in [
            ("inbound_rate_usd", body.inbound_rate_usd),
            ("outbound_rate_usd", body.outbound_rate_usd),
            ("sms_inbound_rate_usd", body.sms_inbound_rate_usd),
            ("sms_outbound_rate_usd", body.sms_outbound_rate_usd),
        ]:
            if val < 0:
                raise HTTPException(status_code=422, detail=f"{field} must be >= 0")

        if body.monthly_alert_threshold_usd is not None and body.monthly_alert_threshold_usd < 0:
            raise HTTPException(status_code=422, detail="monthly_alert_threshold_usd must be >= 0")

        new_config = AccountBillingConfig(
            id=uuid.uuid4(),
            account_id=account_id,
            inbound_rate_usd=body.inbound_rate_usd,
            outbound_rate_usd=body.outbound_rate_usd,
            sms_inbound_rate_usd=body.sms_inbound_rate_usd,
            sms_outbound_rate_usd=body.sms_outbound_rate_usd,
            monthly_alert_threshold_usd=body.monthly_alert_threshold_usd,
            effective_from=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db.add(new_config)
        db.commit()
        db.refresh(new_config)

        logger.info(
            "Admin {} created billing config for account {}: in={} out={} sms_in={} sms_out={}",
            admin.id,
            account_id,
            body.inbound_rate_usd,
            body.outbound_rate_usd,
            body.sms_inbound_rate_usd,
            body.sms_outbound_rate_usd,
        )
        return new_config.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Admin billing config PUT error for {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update billing config")

"""
SMS Analytics endpoints.

  GET /api/sms/stats            — Aggregated analytics
  GET /api/sms/export           — CSV export (max 10,000 rows)
  GET /api/sms/pending-handoffs — Count of conversations needing attention
  GET /api/sms/unread-count     — Count of conversations with unread messages
"""

import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models.sms_conversation import SMSConversation, SMSMessage, ConversationStatus

router = APIRouter(prefix="/api/sms", tags=["SMS"])


@router.get("/pending-handoffs")
async def get_pending_handoffs(
    account_id: str = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Return count of active conversations waiting for a human agent."""
    count = db.query(func.count(SMSConversation.id)).filter(
        SMSConversation.account_id == UUID(account_id),
        SMSConversation.needs_attention == True,
        SMSConversation.status == ConversationStatus.ACTIVE.value,
    ).scalar() or 0
    return {"count": count}


@router.get("/unread-count")
async def get_unread_count(
    account_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """Count of active conversations with messages newer than last_read_at."""
    count = db.query(func.count(SMSConversation.id)).filter(
        SMSConversation.account_id == UUID(account_id),
        SMSConversation.status == ConversationStatus.ACTIVE.value,
        SMSConversation.last_message_at > func.coalesce(
            SMSConversation.last_read_at,
            datetime(2000, 1, 1),
        ),
    ).scalar() or 0
    return {"unread_count": count}


@router.get("/stats")
async def get_sms_stats(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    date_from: Optional[datetime] = Query(None, description="Start of reporting window (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End of reporting window (ISO 8601)"),
    assistant_ids: Optional[List[UUID]] = Query(None, description="Filter to these assistants (repeat param for multiple)."),
    botelier_number: Optional[str] = Query(None, description="Limit stats to one phone number"),
    db: Session = Depends(get_db),
):
    """
    Aggregated analytics for SMS conversations.

    All figures are scoped to account_id. Optional filters narrow the window
    by date range, assistant, or account phone number.
    """
    try:
        from botelier.models.assistant import Assistant
        from botelier.models.disposition import AssistantDisposition

        # Resolve & clamp date range (max 365 days)
        _MAX_RANGE_DAYS = 365
        _now = datetime.utcnow()
        _since = date_from if date_from else (_now - timedelta(days=7))
        _until = date_to if date_to else _now
        if (_until - _since).days > _MAX_RANGE_DAYS:
            _since = _until - timedelta(days=_MAX_RANGE_DAYS)

        def _base_q():
            q = db.query(SMSConversation).filter(SMSConversation.account_id == account_id)
            q = q.filter(SMSConversation.started_at >= _since)
            q = q.filter(SMSConversation.started_at <= _until)
            if assistant_ids:
                q = q.filter(SMSConversation.assistant_id.in_(assistant_ids))
            if botelier_number:
                q = q.filter(SMSConversation.botelier_number == botelier_number)
            return q

        conv_ids_subq = _base_q().with_entities(SMSConversation.id).subquery()

        # --- Overview counts ---
        status_counts = (
            _base_q()
            .with_entities(SMSConversation.status, func.count(SMSConversation.id))
            .group_by(SMSConversation.status)
            .all()
        )
        status_map = {s: c for s, c in status_counts}
        total_conversations = sum(status_map.values())

        handler_counts = (
            _base_q()
            .with_entities(SMSConversation.handler_mode, func.count(SMSConversation.id))
            .group_by(SMSConversation.handler_mode)
            .all()
        )
        handler_map = {h: c for h, c in handler_counts}

        conv_agg = (
            _base_q()
            .with_entities(
                func.sum(SMSConversation.message_count).label("total_msg"),
                func.avg(SMSConversation.message_count).label("avg_msg"),
            )
            .one()
        )

        # Escalation metrics
        currently_needs_attention = (
            _base_q()
            .filter(SMSConversation.needs_attention == True)
            .filter(SMSConversation.status == ConversationStatus.ACTIVE.value)
            .count()
        )
        total_escalated = handler_map.get("human", 0)
        escalation_rate_pct = (
            round(total_escalated / total_conversations * 100, 1)
            if total_conversations > 0 else 0.0
        )

        # --- Message-level stats ---
        msg_agg = (
            db.query(
                SMSMessage.direction,
                SMSMessage.sender,
                func.count(SMSMessage.id).label("cnt"),
                func.sum(SMSMessage.tokens_used).label("tokens"),
            )
            .filter(SMSMessage.conversation_id.in_(conv_ids_subq))
            .group_by(SMSMessage.direction, SMSMessage.sender)
            .all()
        )

        inbound_total  = sum(r.cnt for r in msg_agg if r.direction == "inbound")
        outbound_total = sum(r.cnt for r in msg_agg if r.direction == "outbound")
        ai_responses   = sum(r.cnt for r in msg_agg if r.sender == "ai")
        agent_responses = sum(r.cnt for r in msg_agg if r.sender == "agent")
        total_tokens   = sum((r.tokens or 0) for r in msg_agg)

        # --- Response time ---
        rt_row = (
            _base_q()
            .filter(SMSConversation.first_response_at.isnot(None))
            .with_entities(
                func.avg(
                    func.extract("epoch", SMSConversation.first_response_at - SMSConversation.started_at)
                ).label("avg_rt"),
                func.count(SMSConversation.id).label("cnt"),
            )
            .one()
        )

        # --- Volume by day ---
        day_label = func.date_trunc("day", SMSConversation.started_at).label("day")
        volume_rows = (
            _base_q()
            .with_entities(day_label, func.count(SMSConversation.id).label("conv_count"))
            .group_by("day")
            .order_by("day")
            .all()
        )

        msg_day_label = func.date_trunc("day", SMSMessage.created_at).label("day")
        msg_volume_rows = (
            db.query(msg_day_label, func.count(SMSMessage.id).label("msg_count"))
            .filter(SMSMessage.conversation_id.in_(conv_ids_subq))
            .group_by("day")
            .order_by("day")
            .all()
        )
        msg_volume_map = {
            r.day.date().isoformat() if r.day else None: r.msg_count
            for r in msg_volume_rows
        }

        volume_by_day = [
            {
                "date": r.day.date().isoformat() if r.day else None,
                "conversations_started": r.conv_count,
                "messages": msg_volume_map.get(r.day.date().isoformat() if r.day else None, 0),
            }
            for r in volume_rows
        ]

        # --- By phone number ---
        by_number_rows = (
            _base_q()
            .with_entities(
                SMSConversation.botelier_number,
                func.count(SMSConversation.id).label("conv_count"),
                func.sum(SMSConversation.message_count).label("msg_count"),
            )
            .group_by(SMSConversation.botelier_number)
            .order_by(desc("conv_count"))
            .all()
        )

        # --- By assistant ---
        by_asst_rows = (
            _base_q()
            .filter(SMSConversation.assistant_id.isnot(None))
            .with_entities(
                SMSConversation.assistant_id,
                func.count(SMSConversation.id).label("conv_count"),
            )
            .group_by(SMSConversation.assistant_id)
            .order_by(desc("conv_count"))
            .all()
        )

        asst_ids = [r.assistant_id for r in by_asst_rows]
        asst_names: dict = {}
        if asst_ids:
            arows = db.query(Assistant.id, Assistant.name).filter(Assistant.id.in_(asst_ids)).all()
            asst_names = {str(a.id): a.name for a in arows}

        # --- Dispositions ---
        disp_rows = (
            _base_q()
            .filter(SMSConversation.disposition_id.isnot(None))
            .with_entities(
                SMSConversation.disposition_id,
                func.count(SMSConversation.id).label("cnt"),
            )
            .group_by(SMSConversation.disposition_id)
            .order_by(desc("cnt"))
            .all()
        )

        disp_ids = [r.disposition_id for r in disp_rows]
        disp_info: dict = {}
        if disp_ids:
            disps = db.query(AssistantDisposition).filter(AssistantDisposition.id.in_(disp_ids)).all()
            disp_info = {str(d.id): {"name": d.name, "color": d.color} for d in disps}

        # --- Top customers ---
        top_customers = (
            _base_q()
            .with_entities(
                SMSConversation.customer_number,
                func.count(SMSConversation.id).label("conversation_count"),
                func.sum(SMSConversation.message_count).label("message_count"),
            )
            .group_by(SMSConversation.customer_number)
            .order_by(desc("conversation_count"))
            .limit(20)
            .all()
        )

        avg_rt = float(rt_row.avg_rt) if rt_row.avg_rt else None

        return {
            "period": {
                "from": date_from.isoformat() if date_from else None,
                "to":   date_to.isoformat() if date_to else None,
            },
            "overview": {
                "total_conversations": total_conversations,
                "active":      status_map.get("active",    0),
                "closed":      status_map.get("closed",    0),
                "opted_out":   status_map.get("opted_out", 0),
                "ai_handled":  handler_map.get("ai",    0),
                "human_handled": handler_map.get("human", 0),
                "total_escalated": total_escalated,
                "escalation_rate_pct": escalation_rate_pct,
                "currently_needs_attention": currently_needs_attention,
                "total_messages": int(conv_agg.total_msg or 0),
                "inbound_messages":  inbound_total,
                "outbound_messages": outbound_total,
                "ai_responses":    ai_responses,
                "agent_responses": agent_responses,
                "avg_messages_per_conversation": round(float(conv_agg.avg_msg or 0), 2),
                "total_tokens_used": int(total_tokens),
            },
            "volume_by_day": volume_by_day,
            "response_time": {
                "avg_first_response_seconds": round(avg_rt, 1) if avg_rt is not None else None,
                "conversations_with_response": rt_row.cnt,
            },
            "by_phone_number": [
                {
                    "botelier_number": r.botelier_number,
                    "conversations":   r.conv_count,
                    "messages": int(r.msg_count or 0),
                }
                for r in by_number_rows
            ],
            "by_assistant": [
                {
                    "assistant_id":   str(r.assistant_id),
                    "assistant_name": asst_names.get(str(r.assistant_id), "Unknown"),
                    "conversations":  r.conv_count,
                }
                for r in by_asst_rows
            ],
            "dispositions": [
                {
                    "disposition_id": str(r.disposition_id),
                    "name":  disp_info.get(str(r.disposition_id), {}).get("name", "Unknown"),
                    "color": disp_info.get(str(r.disposition_id), {}).get("color"),
                    "count": r.cnt,
                }
                for r in disp_rows
            ],
            "top_customers": [
                {
                    "customer_number":    r.customer_number,
                    "conversation_count": r.conversation_count,
                    "message_count": int(r.message_count or 0),
                }
                for r in top_customers
            ],
        }

    except Exception as e:
        logger.exception(f"Error generating SMS stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate SMS stats")


@router.get("/export")
async def export_sms_conversations(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    status: Optional[str] = Query(None),
    assistant_id: Optional[UUID] = Query(None),
    handler_mode: Optional[str] = Query(None),
    botelier_number: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Export SMS conversations as a CSV file (max 10,000 rows).

    Columns:
      id, started_at, closed_at, status, handler_mode, needs_attention,
      customer_number, botelier_number, message_count, first_response_at,
      response_time_seconds, ai_responses, agent_responses, tools_used,
      disposition, ai_summary, assistant_id
    """
    try:
        query = db.query(SMSConversation).filter(SMSConversation.account_id == account_id)

        if status:
            query = query.filter(SMSConversation.status == status)
        if assistant_id:
            query = query.filter(SMSConversation.assistant_id == assistant_id)
        if handler_mode and handler_mode in ("ai", "human"):
            query = query.filter(SMSConversation.handler_mode == handler_mode)
        if botelier_number:
            query = query.filter(SMSConversation.botelier_number == botelier_number)
        if date_from:
            query = query.filter(SMSConversation.started_at >= date_from)
        if date_to:
            query = query.filter(SMSConversation.started_at <= date_to)

        conversations = query.order_by(desc(SMSConversation.started_at)).limit(10_000).all()

        conv_ids = [c.id for c in conversations]
        sender_counts: dict = {}
        if conv_ids:
            rows = (
                db.query(
                    SMSMessage.conversation_id,
                    SMSMessage.sender,
                    func.count(SMSMessage.id).label("cnt"),
                )
                .filter(SMSMessage.conversation_id.in_(conv_ids))
                .group_by(SMSMessage.conversation_id, SMSMessage.sender)
                .all()
            )
            for r in rows:
                cid = str(r.conversation_id)
                sender_counts.setdefault(cid, {})[r.sender] = r.cnt

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "started_at", "closed_at", "status", "handler_mode", "needs_attention",
            "customer_number", "botelier_number", "message_count",
            "first_response_at", "response_time_seconds",
            "ai_responses", "agent_responses", "tools_used",
            "disposition", "ai_summary", "assistant_id",
        ])

        for conv in conversations:
            cid = str(conv.id)
            counts = sender_counts.get(cid, {})
            response_time = None
            if conv.first_response_at and conv.started_at:
                response_time = round((conv.first_response_at - conv.started_at).total_seconds(), 1)

            writer.writerow([
                cid,
                conv.started_at.isoformat() + "Z" if conv.started_at else "",
                conv.closed_at.isoformat() + "Z" if conv.closed_at else "",
                conv.status or "",
                conv.handler_mode or "ai",
                "true" if conv.needs_attention else "false",
                conv.customer_number or "",
                conv.botelier_number or "",
                conv.message_count or 0,
                conv.first_response_at.isoformat() + "Z" if conv.first_response_at else "",
                response_time if response_time is not None else "",
                counts.get("ai", 0),
                counts.get("agent", 0),
                conv.tools_used or "",
                conv.disposition.name if conv.disposition else "",
                (conv.ai_summary or "").replace("\n", " "),
                str(conv.assistant_id) if conv.assistant_id else "",
            ])

        filename = f"sms-conversations-{datetime.utcnow().date().isoformat()}.csv"
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.exception(f"Error exporting SMS conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to export conversations")

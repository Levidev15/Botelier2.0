"""
Analytics API — rich aggregated metrics for Call Analytics dashboard.

GET /api/analytics/calls — All call metrics in one response.
"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import desc, func, case, cast, Integer
from sqlalchemy.orm import Session

from botelier.database import get_db
from botelier.models import CallLog, CallStatus, Assistant, AssistantDisposition

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/calls")
async def get_call_analytics(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    db: Session = Depends(get_db),
):
    try:
        since = datetime.utcnow() - timedelta(days=days)

        def _base():
            q = db.query(CallLog).filter(
                CallLog.hotel_id == hotel_id,
                CallLog.started_at >= since,
            )
            if assistant_id:
                q = q.filter(CallLog.assistant_id == assistant_id)
            return q

        total = _base().count()
        completed = _base().filter(CallLog.status == CallStatus.COMPLETED.value).count()
        missed = _base().filter(
            CallLog.status.in_([
                CallStatus.NO_ANSWER.value,
                CallStatus.BUSY.value,
                CallStatus.CANCELED.value,
            ])
        ).count()
        failed = _base().filter(CallLog.status == CallStatus.FAILED.value).count()
        transferred = _base().filter(CallLog.has_transfer == True).count()

        dur_row = (
            _base()
            .with_entities(
                func.coalesce(func.avg(CallLog.duration_seconds), 0).label("avg"),
                func.coalesce(func.sum(CallLog.duration_seconds), 0).label("total"),
            )
            .one()
        )

        overview = {
            "total_calls": total,
            "completed": completed,
            "missed": missed,
            "failed": failed,
            "transferred": transferred,
            "completion_rate": round(completed / total * 100, 1) if total else 0,
            "transfer_rate": round(transferred / total * 100, 1) if total else 0,
            "avg_duration_seconds": round(float(dur_row.avg), 1),
            "total_duration_seconds": int(dur_row.total),
        }

        day_label = func.date_trunc("day", CallLog.started_at).label("day")
        vol_rows = (
            _base()
            .with_entities(day_label, func.count(CallLog.id).label("cnt"))
            .group_by("day")
            .order_by("day")
            .all()
        )
        volume_by_day = [
            {"date": r.day.date().isoformat(), "calls": r.cnt}
            for r in vol_rows
        ]

        hour_label = func.extract("hour", CallLog.started_at).label("hr")
        hour_rows = (
            _base()
            .with_entities(hour_label, func.count(CallLog.id).label("cnt"))
            .group_by("hr")
            .order_by("hr")
            .all()
        )
        calls_by_hour = [
            {"hour": int(r.hr), "calls": r.cnt}
            for r in hour_rows
        ]

        status_rows = (
            _base()
            .with_entities(CallLog.status, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.status)
            .order_by(desc("cnt"))
            .all()
        )
        status_distribution = [
            {"status": r.status, "count": r.cnt}
            for r in status_rows
        ]

        asst_rows = (
            _base()
            .filter(CallLog.assistant_id.isnot(None))
            .with_entities(CallLog.assistant_id, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.assistant_id)
            .order_by(desc("cnt"))
            .all()
        )
        asst_ids = [r.assistant_id for r in asst_rows]
        asst_names: dict = {}
        if asst_ids:
            arows = db.query(Assistant.id, Assistant.name).filter(Assistant.id.in_(asst_ids)).all()
            asst_names = {str(a.id): a.name for a in arows}

        by_assistant = [
            {
                "assistant_id": str(r.assistant_id),
                "assistant_name": asst_names.get(str(r.assistant_id), "Unknown"),
                "calls": r.cnt,
            }
            for r in asst_rows
        ]

        disp_rows = (
            _base()
            .filter(CallLog.disposition_id.isnot(None))
            .with_entities(CallLog.disposition_id, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.disposition_id)
            .order_by(desc("cnt"))
            .all()
        )
        disp_ids = [r.disposition_id for r in disp_rows]
        disp_info: dict = {}
        if disp_ids:
            disps = db.query(AssistantDisposition).filter(AssistantDisposition.id.in_(disp_ids)).all()
            disp_info = {str(d.id): {"name": d.name, "color": d.color} for d in disps}

        dispositions = [
            {
                "disposition_id": str(r.disposition_id),
                "name": disp_info.get(str(r.disposition_id), {}).get("name", "Unknown"),
                "color": disp_info.get(str(r.disposition_id), {}).get("color"),
                "count": r.cnt,
            }
            for r in disp_rows
        ]

        acw_base = _base().filter(CallLog.acw_completed_at.isnot(None))
        acw_total = acw_base.count()

        score_row = acw_base.with_entities(
            func.avg(CallLog.acw_quality_score).label("avg"),
            func.min(CallLog.acw_quality_score).label("mn"),
            func.max(CallLog.acw_quality_score).label("mx"),
        ).one()

        res_rows = (
            acw_base
            .filter(CallLog.acw_resolution.isnot(None))
            .with_entities(CallLog.acw_resolution, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.acw_resolution)
            .order_by(desc("cnt"))
            .all()
        )

        buckets = [
            ("0-20", 0, 20),
            ("21-40", 21, 40),
            ("41-60", 41, 60),
            ("61-80", 61, 80),
            ("81-100", 81, 100),
        ]
        score_dist_cases = [
            func.sum(
                case(
                    (
                        (CallLog.acw_quality_score >= lo) & (CallLog.acw_quality_score <= hi),
                        1,
                    ),
                    else_=0,
                )
            ).label(label)
            for label, lo, hi in buckets
        ]

        score_dist_row = acw_base.with_entities(*score_dist_cases).one() if acw_total else None

        score_distribution = []
        if score_dist_row:
            for i, (label, _, _) in enumerate(buckets):
                score_distribution.append({"range": label, "count": int(score_dist_row[i] or 0)})

        acw_completion_rate = round(acw_total / total * 100, 1) if total else 0

        acw = {
            "acw_completed": acw_total,
            "acw_completion_rate": acw_completion_rate,
            "avg_quality_score": round(float(score_row.avg), 1) if score_row.avg else None,
            "min_quality_score": int(score_row.mn) if score_row.mn is not None else None,
            "max_quality_score": int(score_row.mx) if score_row.mx is not None else None,
            "resolution_distribution": [
                {"resolution": r.acw_resolution, "count": r.cnt}
                for r in res_rows
            ],
            "score_distribution": score_distribution,
        }

        return {
            "period_days": days,
            "overview": overview,
            "volume_by_day": volume_by_day,
            "calls_by_hour": calls_by_hour,
            "status_distribution": status_distribution,
            "by_assistant": by_assistant,
            "dispositions": dispositions,
            "acw": acw,
        }

    except Exception as e:
        logger.exception(f"Error generating call analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate call analytics")

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import Optional
import asyncio

from botelier.database import get_db
from botelier.auth.middleware import get_current_user
from botelier.models.queue_report import QueuePerformanceReport
from botelier.models.integration import AccountIntegration, IntegrationType, IntegrationStatus
from botelier.services.zoom_reports import fetch_queue_performance, fetch_queue_list

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_account_id(current_user) -> str:
    memberships = getattr(current_user, "account_memberships", None) or []
    active = [m for m in memberships if getattr(m, "is_active", False)]
    if active:
        return str(active[0].account_id)
    return None


@router.get("/queue-performance")
async def get_queue_performance_reports(
    days: int = Query(default=7, ge=1, le=90),
    queue_id: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(QueuePerformanceReport).filter(
        QueuePerformanceReport.account_id == account_id,
        QueuePerformanceReport.fetched_at >= since,
    )
    if queue_id:
        query = query.filter(QueuePerformanceReport.queue_id == queue_id)

    reports = query.order_by(desc(QueuePerformanceReport.report_period_start)).limit(500).all()

    return [_serialize_report(r) for r in reports]


@router.get("/queue-performance/summary")
async def get_queue_performance_summary(
    days: int = Query(default=7, ge=1, le=90),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    since = datetime.utcnow() - timedelta(days=days)

    results = (
        db.query(
            QueuePerformanceReport.queue_id,
            QueuePerformanceReport.queue_name,
            func.sum(QueuePerformanceReport.total_calls).label("total_calls"),
            func.sum(QueuePerformanceReport.calls_answered).label("calls_answered"),
            func.sum(QueuePerformanceReport.calls_abandoned).label("calls_abandoned"),
            func.sum(QueuePerformanceReport.calls_transferred).label("calls_transferred"),
            func.avg(QueuePerformanceReport.avg_wait_time_seconds).label("avg_wait"),
            func.max(QueuePerformanceReport.max_wait_time_seconds).label("max_wait"),
            func.avg(QueuePerformanceReport.avg_handle_time_seconds).label("avg_handle"),
            func.avg(QueuePerformanceReport.service_level_pct).label("avg_service_level"),
            func.avg(QueuePerformanceReport.abandon_rate_pct).label("avg_abandon_rate"),
            func.avg(QueuePerformanceReport.answer_rate_pct).label("avg_answer_rate"),
            func.count().label("report_count"),
        )
        .filter(
            QueuePerformanceReport.account_id == account_id,
            QueuePerformanceReport.fetched_at >= since,
        )
        .group_by(QueuePerformanceReport.queue_id, QueuePerformanceReport.queue_name)
        .all()
    )

    return [
        {
            "queue_id": r.queue_id,
            "queue_name": r.queue_name,
            "total_calls": int(r.total_calls or 0),
            "calls_answered": int(r.calls_answered or 0),
            "calls_abandoned": int(r.calls_abandoned or 0),
            "calls_transferred": int(r.calls_transferred or 0),
            "avg_wait_time_seconds": round(float(r.avg_wait or 0), 1),
            "max_wait_time_seconds": round(float(r.max_wait or 0), 1),
            "avg_handle_time_seconds": round(float(r.avg_handle or 0), 1),
            "avg_service_level_pct": round(float(r.avg_service_level or 0), 1),
            "avg_abandon_rate_pct": round(float(r.avg_abandon_rate or 0), 1),
            "avg_answer_rate_pct": round(float(r.avg_answer_rate or 0), 1),
            "report_count": r.report_count,
        }
        for r in results
    ]


@router.get("/queue-performance/trend")
async def get_queue_performance_trend(
    days: int = Query(default=7, ge=1, le=90),
    queue_id: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(QueuePerformanceReport).filter(
        QueuePerformanceReport.account_id == account_id,
        QueuePerformanceReport.fetched_at >= since,
    )
    if queue_id:
        query = query.filter(QueuePerformanceReport.queue_id == queue_id)

    reports = query.order_by(QueuePerformanceReport.report_period_start).limit(500).all()

    trend = []
    for r in reports:
        trend.append({
            "timestamp": r.report_period_start.isoformat() if r.report_period_start else None,
            "queue_name": r.queue_name,
            "total_calls": r.total_calls,
            "calls_answered": r.calls_answered,
            "calls_abandoned": r.calls_abandoned,
            "avg_wait_time": round(r.avg_wait_time_seconds or 0, 1),
            "avg_handle_time": round(r.avg_handle_time_seconds or 0, 1),
            "service_level": round(r.service_level_pct or 0, 1),
            "abandon_rate": round(r.abandon_rate_pct or 0, 1),
        })

    return trend


@router.post("/queue-performance/refresh")
async def refresh_queue_performance(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    connections = (
        db.query(AccountIntegration)
        .join(IntegrationType)
        .filter(
            AccountIntegration.account_id == account_id,
            IntegrationType.slug == "zoom-contact-center",
            AccountIntegration.status == IntegrationStatus.CONNECTED,
        )
        .all()
    )

    if not connections:
        raise HTTPException(
            status_code=404,
            detail="No active Zoom Contact Center connection found. Please connect your Zoom account in Integrations first.",
        )

    total_reports = 0
    errors = []
    for conn in connections:
        try:
            reports = await fetch_queue_performance(conn, db)
            total_reports += len(reports)
        except Exception as e:
            errors.append(str(e))

    return {
        "success": True,
        "reports_fetched": total_reports,
        "connections_processed": len(connections),
        "errors": errors if errors else None,
    }


@router.get("/zoom/queues")
async def list_zoom_queues(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    connection = (
        db.query(AccountIntegration)
        .join(IntegrationType)
        .filter(
            AccountIntegration.account_id == account_id,
            IntegrationType.slug == "zoom-contact-center",
            AccountIntegration.status == IntegrationStatus.CONNECTED,
        )
        .first()
    )

    if not connection:
        return []

    queues = await fetch_queue_list(connection, db)
    return queues


@router.get("/zoom/status")
async def get_zoom_report_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account_id = _get_account_id(current_user)
    if not account_id:
        raise HTTPException(status_code=403, detail="No active account")

    connection = (
        db.query(AccountIntegration)
        .join(IntegrationType)
        .filter(
            AccountIntegration.account_id == account_id,
            IntegrationType.slug == "zoom-contact-center",
        )
        .first()
    )

    last_report = (
        db.query(QueuePerformanceReport)
        .filter(QueuePerformanceReport.account_id == account_id)
        .order_by(desc(QueuePerformanceReport.fetched_at))
        .first()
    )

    total_reports = (
        db.query(func.count(QueuePerformanceReport.id))
        .filter(QueuePerformanceReport.account_id == account_id)
        .scalar()
    )

    return {
        "connected": connection is not None and connection.status == IntegrationStatus.CONNECTED,
        "connection_status": connection.status.value if connection else "not_configured",
        "last_sync": connection.last_sync_at.isoformat() if connection and connection.last_sync_at else None,
        "last_report_at": last_report.fetched_at.isoformat() if last_report else None,
        "total_reports": total_reports or 0,
    }


def _serialize_report(r: QueuePerformanceReport) -> dict:
    return {
        "id": str(r.id),
        "queue_id": r.queue_id,
        "queue_name": r.queue_name,
        "report_period_start": r.report_period_start.isoformat() if r.report_period_start else None,
        "report_period_end": r.report_period_end.isoformat() if r.report_period_end else None,
        "total_calls": r.total_calls,
        "calls_answered": r.calls_answered,
        "calls_abandoned": r.calls_abandoned,
        "calls_transferred": r.calls_transferred,
        "calls_overflowed": r.calls_overflowed,
        "avg_wait_time_seconds": round(r.avg_wait_time_seconds or 0, 1),
        "max_wait_time_seconds": round(r.max_wait_time_seconds or 0, 1),
        "avg_handle_time_seconds": round(r.avg_handle_time_seconds or 0, 1),
        "avg_talk_time_seconds": round(r.avg_talk_time_seconds or 0, 1),
        "avg_hold_time_seconds": round(r.avg_hold_time_seconds or 0, 1),
        "avg_wrap_time_seconds": round(r.avg_wrap_time_seconds or 0, 1),
        "service_level_pct": round(r.service_level_pct or 0, 1),
        "abandon_rate_pct": round(r.abandon_rate_pct or 0, 1),
        "answer_rate_pct": round(r.answer_rate_pct or 0, 1),
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
    }

"""Admin — Call Duration Reconciliation API.

POST /api/admin/reconcile-durations           — start a dry-run or apply run
GET  /api/admin/reconcile-durations           — list recent runs (newest first)
GET  /api/admin/reconcile-durations/{run_id}  — poll status + full summary for one run
GET  /api/admin/reconcile-durations/{run_id}/results — per-call detail for a run

Workflow:
  1. POST with mode="dry_run" → returns a completed run with summary of what would change.
  2. Review the summary (and optionally the per-call results via GET /{run_id}/results).
  3. POST with mode="apply" and approved_run_id=<dry_run_id> → applies the corrections.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from botelier.auth.middleware import get_platform_admin
from botelier.database import get_db
from botelier.models.billing import (
    CallDurationReconciliationResult,
    CallDurationReconciliationRun,
)
from botelier.models.user import User
from botelier.services.call_duration_reconciliation import CallDurationReconciler

router = APIRouter(
    prefix="/api/admin/reconcile-durations",
    tags=["Admin — Duration Reconciliation"],
)


class ReconcileRequest(BaseModel):
    mode: str = "dry_run"
    account_id: Optional[UUID] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    call_sid: Optional[str] = None
    batch_size: int = 100
    resume_after: Optional[str] = None
    approved_run_id: Optional[UUID] = None


def _serialize_run(run: CallDurationReconciliationRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "status": run.status,
        "mode": run.mode,
        "account_id": str(run.account_id) if run.account_id else None,
        "date_from": run.date_from.isoformat() if run.date_from else None,
        "date_to": run.date_to.isoformat() if run.date_to else None,
        "call_sid": run.call_sid,
        "batch_size": run.batch_size,
        "resume_after": run.resume_after,
        "summary": run.summary or {},
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _serialize_result(result: CallDurationReconciliationResult) -> dict[str, Any]:
    return {
        "result_id": str(result.id),
        "call_log_id": str(result.call_log_id),
        "account_id": str(result.account_id) if result.account_id else None,
        "call_sid": result.call_sid,
        "status": result.status,
        "old_values": result.old_values or {},
        "new_values": result.new_values or {},
        "provider_evidence": result.provider_evidence or {},
        "error_message": result.error_message,
    }


@router.post("")
async def start_reconciliation(
    body: ReconcileRequest,
    user: User = Depends(get_platform_admin),
):
    """Start a call-duration reconciliation run and wait for it to complete.

    mode=dry_run (default): fetches Twilio evidence and computes what would change —
        nothing is written to the database.
    mode=apply: applies the corrections from a completed dry run.
        Requires approved_run_id pointing to a completed, zero-failed dry run whose
        scope (account_id, date_from, date_to, call_sid, batch_size, resume_after)
        exactly matches this request.

    The endpoint blocks until the run completes (runs in a thread to avoid blocking
    the event loop). For large datasets use batch_size and resume_after to paginate.
    """
    if body.mode not in ("dry_run", "apply"):
        raise HTTPException(status_code=422, detail="mode must be 'dry_run' or 'apply'")
    if body.mode == "apply" and body.approved_run_id is None:
        raise HTTPException(
            status_code=422,
            detail="mode='apply' requires approved_run_id from a completed dry run",
        )

    service = CallDurationReconciler()
    try:
        run = await run_in_threadpool(
            service.run,
            mode=body.mode,
            account_id=body.account_id,
            date_from=body.date_from,
            date_to=body.date_to,
            call_sid=body.call_sid,
            batch_size=min(max(1, body.batch_size), 500),
            resume_after=body.resume_after,
            approved_run_id=body.approved_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception(f"Reconciliation run failed unexpectedly: {exc}")
        raise HTTPException(status_code=500, detail="Reconciliation run failed")

    return _serialize_run(run)


@router.get("")
async def list_runs(
    account_id: Optional[UUID] = Query(None, description="Filter to one account"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Return recent reconciliation runs, newest first."""
    q = db.query(CallDurationReconciliationRun).order_by(
        CallDurationReconciliationRun.started_at.desc()
    )
    if account_id is not None:
        q = q.filter(CallDurationReconciliationRun.account_id == account_id)
    runs = q.limit(limit).all()
    return [_serialize_run(r) for r in runs]


@router.get("/{run_id}")
async def get_run(
    run_id: UUID,
    user: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Return status and summary for a single reconciliation run."""
    run = (
        db.query(CallDurationReconciliationRun)
        .filter(CallDurationReconciliationRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return _serialize_run(run)


@router.get("/{run_id}/results")
async def get_run_results(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by result status (planned, applied, unresolved, failed)"),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_platform_admin),
    db: Session = Depends(get_db),
):
    """Return per-call before/after evidence for a reconciliation run.

    Use this to review what a dry run would change before approving it.
    """
    run = (
        db.query(CallDurationReconciliationRun)
        .filter(CallDurationReconciliationRun.id == run_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")

    q = db.query(CallDurationReconciliationResult).filter(
        CallDurationReconciliationResult.run_id == run_id
    )
    if status is not None:
        q = q.filter(CallDurationReconciliationResult.status == status)
    results = q.limit(limit).all()
    return {
        "run_id": str(run_id),
        "run_status": run.status,
        "results": [_serialize_result(r) for r in results],
    }

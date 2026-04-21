"""
Call Logs API - CRUD operations for call history.

SECURITY: All endpoints enforce account_id filtering to prevent cross-tenant data access.
This is critical for multi-tenant isolation in the SaaS platform.
"""

import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, or_, func, Text
from sqlalchemy.orm import Session, joinedload
from loguru import logger

from botelier.database import get_db
from botelier.models import CallLog, CallLeg, CallStatus, Assistant, PhoneNumber, AssistantDisposition
from botelier.models.resolution_option import AssistantResolutionOption
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission
from botelier.models.role import AccountMembership
from botelier.api.analytics import (
    _bucket_predicate,
    _silent_caller_predicate,
    _PARTITION_BUCKETS,
    _classify_partition,
)


router = APIRouter(prefix="/api/call-logs", tags=["Call Logs"])


_MISSED_STATUSES = ("no_answer", "busy", "canceled")

# Task #102 — bucket tokens accepted by GET /api/call-logs?bucket=...
# Derived from the analytics module's `_PARTITION_BUCKETS` tuple plus the
# `silent_caller` sub-bucket so adding a new MECE bucket in analytics
# automatically extends the Call Logs filter contract — no second list to
# keep in sync. Reuses the canonical predicates from analytics; never
# re-implements the SQL.
_BUCKET_TOKENS = tuple(_PARTITION_BUCKETS) + ("silent_caller",)


def _can_view_transcripts(user: User, account_id: str, db: Session) -> bool:
    """Return True if user has call_logs.view_transcripts for this account."""
    if user.is_platform_admin:
        return True
    membership = db.query(AccountMembership).filter(
        AccountMembership.user_id == user.id,
        AccountMembership.account_id == account_id,
        AccountMembership.is_active == True,
    ).first()
    if not membership:
        return False
    return membership.has_permission("call_logs.view_transcripts")


@router.get("")
async def get_call_logs(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by call status. Use 'missed' to match no_answer|busy|canceled."),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    phone_number_id: Optional[UUID] = Query(None, description="Filter by phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter calls from this date"),
    date_to: Optional[datetime] = Query(None, description="Filter calls until this date"),
    search: Optional[str] = Query(None, description="Search caller number or transcript"),
    has_transfer: Optional[bool] = Query(None, description="If true, only return calls with transfers"),
    disposition_id: Optional[UUID] = Query(None, description="Filter by disposition UUID"),
    acw_resolution: Optional[str] = Query(None, description="Filter by resolution status string"),
    acw_completed: Optional[bool] = Query(None, description="If true, only return calls with completed Post Call QA"),
    quality_min: Optional[int] = Query(None, ge=0, le=100, description="Minimum ACW quality score"),
    quality_max: Optional[int] = Query(None, ge=0, le=100, description="Maximum ACW quality score"),
    hour: Optional[int] = Query(None, ge=0, le=23, description="Hour of day (0-23) in UTC to filter by"),
    bucket: Optional[str] = Query(None, description=(
        "Task #97 partition bucket — one of: ai_handled, ended_early, missed, "
        "failed, unresolved, silent_caller. Maps 1:1 to the analytics "
        "partition predicates so the row set exactly matches the drilldown."
    )),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get paginated call logs for a hotel."""
    check_account_permission(user, str(account_id), "call_logs.view", db)
    try:
        query = db.query(CallLog).filter(CallLog.account_id == account_id)
        
        if status:
            if status == "missed":
                query = query.filter(CallLog.status.in_(_MISSED_STATUSES))
            else:
                query = query.filter(CallLog.status == status)
        
        if assistant_id:
            query = query.filter(CallLog.assistant_id == assistant_id)
        
        if phone_number_id:
            query = query.filter(CallLog.phone_number_id == phone_number_id)
        
        if date_from:
            query = query.filter(CallLog.started_at >= date_from)
        
        if date_to:
            query = query.filter(CallLog.started_at <= date_to)

        if has_transfer is not None:
            query = query.filter(CallLog.has_transfer == has_transfer)

        if disposition_id:
            query = query.filter(CallLog.disposition_id == disposition_id)

        if acw_resolution:
            query = query.filter(CallLog.acw_resolution == acw_resolution)

        if acw_completed:
            query = query.filter(CallLog.acw_completed_at.isnot(None))

        if quality_min is not None:
            query = query.filter(CallLog.acw_quality_score >= quality_min)

        if quality_max is not None:
            query = query.filter(CallLog.acw_quality_score <= quality_max)

        if hour is not None:
            query = query.filter(func.extract("hour", CallLog.started_at) == hour)

        if bucket:
            tok = bucket.strip()
            if tok not in _BUCKET_TOKENS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid bucket {tok!r}. Must be one of {_BUCKET_TOKENS}.",
                )
            if tok == "silent_caller":
                query = query.filter(_silent_caller_predicate())
            else:
                query = query.filter(_bucket_predicate(tok))
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    CallLog.caller_number.ilike(search_pattern),
                    CallLog.reference_id.ilike(search_pattern),
                    CallLog.transcript.cast(Text).ilike(search_pattern),
                )
            )
        
        total = query.count()
        
        call_logs = (
            query
            .options(joinedload(CallLog.legs), joinedload(CallLog.disposition))
            .order_by(desc(CallLog.started_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        
        assistant_ids = [log.assistant_id for log in call_logs if log.assistant_id]
        phone_ids = [log.phone_number_id for log in call_logs if log.phone_number_id]
        
        assistants = {}
        if assistant_ids:
            assistant_records = db.query(Assistant).filter(
                Assistant.id.in_(assistant_ids),
                Assistant.account_id == account_id
            ).all()
            assistants = {str(a.id): a.name for a in assistant_records}
        
        phone_numbers = {}
        if phone_ids:
            phone_records = db.query(PhoneNumber).filter(
                PhoneNumber.id.in_(phone_ids),
                PhoneNumber.account_id == account_id
            ).all()
            phone_numbers = {str(p.id): p.phone_number for p in phone_records}
        
        include_transcript = _can_view_transcripts(user, str(account_id), db)
        logs_with_names = []
        for log in call_logs:
            log_dict = log.to_dict(include_legs=True, include_transcript=include_transcript)
            log_dict["assistant_name"] = assistants.get(str(log.assistant_id)) if log.assistant_id else None
            log_dict["phone_number_display"] = phone_numbers.get(str(log.phone_number_id)) if log.phone_number_id else None
            logs_with_names.append(log_dict)
        
        return {
            "call_logs": logs_with_names,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        }

    except HTTPException:
        # Preserve intentional 4xx responses (e.g. invalid bucket token)
        # so clients see the validation error instead of a generic 500.
        raise
    except Exception as e:
        logger.exception(f"Error fetching call logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch call logs")


@router.get("/stats")
async def get_call_stats(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get call statistics for quick summary display."""
    check_account_permission(user, str(account_id), "call_logs.view", db)
    try:
        since = datetime.utcnow() - timedelta(days=days)
        
        base_query = db.query(CallLog).filter(
            CallLog.account_id == account_id,
            CallLog.started_at >= since
        )
        
        total_calls = base_query.count()
        completed_calls = base_query.filter(CallLog.status == CallStatus.COMPLETED.value).count()
        transferred_calls = base_query.filter(CallLog.has_transfer == True).count()
        
        total_duration = db.query(func.sum(CallLog.duration_seconds)).filter(
            CallLog.account_id == account_id,
            CallLog.started_at >= since
        ).scalar() or 0
        
        avg_duration = total_duration / total_calls if total_calls > 0 else 0
        
        return {
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "transferred_calls": transferred_calls,
            "total_duration_seconds": total_duration,
            "avg_duration_seconds": round(avg_duration, 1),
            "period_days": days,
        }
        
    except Exception as e:
        logger.exception(f"Error fetching call stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch call statistics")


@router.get("/export")
async def export_call_logs(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    status: Optional[str] = Query(None),
    assistant_id: Optional[UUID] = Query(None),
    # Task #129 — accept the same multi-assistant filter shape as the
    # analytics endpoint so the dashboard's "Detailed CSV" export honors
    # the on-screen Assistant filter without losing rows.
    assistant_ids: Optional[List[UUID]] = Query(
        None, description="Filter to these assistants (repeat param for multiple)."
    ),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    bucket: Optional[str] = Query(
        None,
        description=(
            "Task #129 — partition bucket filter: ai_handled | ended_early | "
            "missed | failed | unresolved | silent_caller. Maps 1:1 to the "
            "analytics partition predicates so the row count matches the "
            "dashboard pill exactly."
        ),
    ),
    disposition_id: Optional[UUID] = Query(None, description="Filter by disposition UUID."),
    caller_spoke: Optional[bool] = Query(
        None,
        description=(
            "Filter on caller_spoke. true = caller produced audio; false = "
            "silent caller; omit = no filter (NULL legacy rows included)."
        ),
    ),
    tz: Optional[str] = Query(  # noqa: A002 — short query name kept to match dashboard
        None,
        description="IANA timezone name. Reserved for future per-row local timestamp column; not used today.",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export call logs as CSV file.

    Task #129 — additive: existing columns and order are preserved so any
    external consumer keeps working. New columns appended on the right:
    Reference ID, Bucket (MECE), Greeted, Caller Spoke, Disposition,
    ACW Resolution, ACW Quality Score, ACW Skip Reason.
    """
    check_account_permission(user, str(account_id), "call_logs.export", db)
    try:
        query = db.query(CallLog).filter(CallLog.account_id == account_id)

        if status:
            query = query.filter(CallLog.status == status)
        if assistant_id:
            query = query.filter(CallLog.assistant_id == assistant_id)
        if assistant_ids:
            query = query.filter(CallLog.assistant_id.in_(assistant_ids))
        if date_from:
            query = query.filter(CallLog.started_at >= date_from)
        if date_to:
            query = query.filter(CallLog.started_at <= date_to)

        # Task #129 — bucket filter shares the canonical predicate with the
        # analytics endpoint so the CSV row count under "Bucket = X"
        # reconciles to the dashboard pill count for X by construction.
        if bucket:
            tok = bucket.strip()
            if tok not in _BUCKET_TOKENS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid bucket {tok!r}. Must be one of {_BUCKET_TOKENS}.",
                )
            if tok == "silent_caller":
                query = query.filter(_silent_caller_predicate())
            else:
                query = query.filter(_bucket_predicate(tok))

        if disposition_id:
            query = query.filter(CallLog.disposition_id == disposition_id)

        if caller_spoke is not None:
            # Explicit TRUE / FALSE filter. NULL (legacy rows) is excluded
            # by both branches — matches PostgreSQL's three-valued logic
            # and the analytics module's silent-caller treatment.
            query = query.filter(CallLog.caller_spoke.is_(caller_spoke))

        call_logs = (
            query.options(
                joinedload(CallLog.legs),
                joinedload(CallLog.disposition),
            )
            .order_by(desc(CallLog.started_at))
            .all()
        )

        asst_id_set = {log.assistant_id for log in call_logs if log.assistant_id}
        assistants: dict = {}
        if asst_id_set:
            records = db.query(Assistant).filter(
                Assistant.id.in_(asst_id_set),
                Assistant.account_id == account_id,
            ).all()
            assistants = {str(a.id): a.name for a in records}

        # Task #129 — bulk-load disposition names rather than re-querying per
        # row. joinedload above also covers this; the explicit map keeps the
        # CSV write loop allocation-free.
        disp_id_set = {log.disposition_id for log in call_logs if log.disposition_id}
        disp_map: dict = {}
        if disp_id_set:
            drows = db.query(AssistantDisposition.id, AssistantDisposition.name).filter(
                AssistantDisposition.id.in_(disp_id_set)
            ).all()
            disp_map = {str(d.id): d.name for d in drows}

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            # Original 12 columns — order preserved (additive contract).
            "Date/Time",
            "Total Duration (seconds)",
            "AI Duration (seconds)",
            "Transfer Duration (seconds)",
            "Caller",
            "To Number",
            "Assistant",
            "Status",
            "Outcome",
            "Has Transfer",
            "Transfer Mode",
            "Leg Count",
            # Task #129 — new columns appended on the right.
            "Reference ID",
            "Bucket (MECE)",
            "Greeted",
            "Caller Spoke",
            "Disposition",
            "ACW Resolution",
            "ACW Quality Score",
            "ACW Skip Reason",
        ])

        for log in call_logs:
            legs = log.legs or []
            leg_count = len(legs)
            ai_duration = sum(
                leg.duration_seconds or 0 for leg in legs
                if leg.leg_type == "ai_conversation"
            )
            transfer_duration = sum(
                leg.duration_seconds or 0 for leg in legs
                if leg.leg_type in ("transfer_external", "transfer_sip", "transfer_internal", "transfer_cold")
            )

            # Task #129 — derive Bucket via the analytics classifier so the
            # CSV's bucket vocabulary matches the dashboard exactly. Pure
            # function call; no extra DB hit.
            bucket_label = _classify_partition(
                log.status or "",
                bool(log.ai_greeting_completed),
                log.caller_spoke,
            )
            # Render NULL caller_spoke as empty string rather than "None" so
            # spreadsheet pivots treat it as missing instead of a third value.
            caller_spoke_cell = (
                "" if log.caller_spoke is None
                else ("Yes" if log.caller_spoke else "No")
            )

            writer.writerow([
                log.started_at.isoformat() if log.started_at else "",
                log.duration_seconds or 0,
                ai_duration,
                transfer_duration,
                log.caller_number or "",
                log.to_number or "",
                assistants.get(str(log.assistant_id), "") if log.assistant_id else "",
                log.status or "",
                log.outcome or "",
                "Yes" if log.has_transfer else "No",
                log.transfer_mode or "",
                leg_count,
                # New (additive) columns:
                log.reference_id or "",
                bucket_label,
                "Yes" if log.ai_greeting_completed else "No",
                caller_spoke_cell,
                disp_map.get(str(log.disposition_id), "") if log.disposition_id else "",
                log.acw_resolution or "",
                "" if log.acw_quality_score is None else log.acw_quality_score,
                log.acw_skip_reason or "",
            ])

        output.seek(0)

        filename = f"call_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        # Preserve intentional 4xx responses (invalid bucket token).
        raise
    except Exception as e:
        logger.exception(f"Error exporting call logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to export call logs")


@router.get("/{call_log_id}")
async def get_call_log(
    call_log_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single call log with full details including transcript and legs."""
    check_account_permission(user, str(account_id), "call_logs.view", db)
    try:
        call_log = (
            db.query(CallLog)
            .options(joinedload(CallLog.legs), joinedload(CallLog.disposition))
            .filter(
                CallLog.id == call_log_id,
                CallLog.account_id == account_id
            )
            .first()
        )
        
        if not call_log:
            raise HTTPException(status_code=404, detail="Call log not found")
        
        include_transcript = _can_view_transcripts(user, str(account_id), db)
        result = call_log.to_dict(include_legs=True, include_transcript=include_transcript)
        
        if call_log.assistant_id:
            assistant = db.query(Assistant).filter(
                Assistant.id == call_log.assistant_id,
                Assistant.account_id == account_id
            ).first()
            result["assistant_name"] = assistant.name if assistant else None
        
        if call_log.phone_number_id:
            phone = db.query(PhoneNumber).filter(
                PhoneNumber.id == call_log.phone_number_id,
                PhoneNumber.account_id == account_id
            ).first()
            result["phone_number_display"] = phone.phone_number if phone else None
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching call log: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch call log")


@router.get("/filters/options")
async def get_filter_options(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    assistant_id: Optional[UUID] = Query(None, description="Scope dispositions and resolutions to this assistant"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get available filter options (assistants, phone numbers, statuses, dispositions, resolutions)."""
    check_account_permission(user, str(account_id), "call_logs.view", db)
    try:
        assistants = db.query(Assistant).filter(
            Assistant.account_id == account_id
        ).order_by(Assistant.name).all()
        
        phone_numbers = db.query(PhoneNumber).filter(
            PhoneNumber.account_id == account_id
        ).order_by(PhoneNumber.phone_number).all()
        
        statuses = [status.value for status in CallStatus]

        disposition_query = db.query(AssistantDisposition).join(
            Assistant, AssistantDisposition.assistant_id == Assistant.id
        ).filter(
            Assistant.account_id == account_id,
            AssistantDisposition.is_active == True,
        )
        if assistant_id:
            disposition_query = disposition_query.filter(
                AssistantDisposition.assistant_id == assistant_id
            )
        dispositions = disposition_query.order_by(AssistantDisposition.name).all()

        resolution_query = db.query(CallLog.acw_resolution).filter(
            CallLog.account_id == account_id,
            CallLog.acw_resolution.isnot(None),
            CallLog.acw_resolution != "",
        )
        if assistant_id:
            resolution_query = resolution_query.filter(
                CallLog.assistant_id == assistant_id
            )
        resolution_rows = resolution_query.distinct().order_by(CallLog.acw_resolution).all()
        resolution_options = [r[0] for r in resolution_rows]

        configured_resolution_options: list = []
        if assistant_id:
            res_opts = (
                db.query(AssistantResolutionOption)
                .filter(AssistantResolutionOption.assistant_id == assistant_id)
                .order_by(AssistantResolutionOption.name)
                .all()
            )
            configured_resolution_options = [r.name for r in res_opts]

        return {
            "assistants": [{"id": str(a.id), "name": a.name} for a in assistants],
            "phone_numbers": [
                {"id": str(p.id), "number": p.phone_number, "name": p.friendly_name}
                for p in phone_numbers
            ],
            "statuses": statuses,
            "dispositions": [
                {"id": str(d.id), "name": d.name, "color": d.color}
                for d in dispositions
            ],
            "resolution_options": resolution_options,
            "configured_resolution_options": configured_resolution_options,
        }
        
    except Exception as e:
        logger.exception(f"Error fetching filter options: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch filter options")


class GenerateSummaryRequest(BaseModel):
    account_id: str


class UpdateCallLogRequest(BaseModel):
    disposition_id: Optional[str] = None
    ai_summary: Optional[str] = None
    acw_resolution: Optional[str] = None
    acw_quality_score: Optional[int] = None


@router.post("/{call_log_id}/generate-summary")
async def generate_summary(
    call_log_id: UUID,
    request: GenerateSummaryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Run Post Call QA on a call transcript.

    Delegates to AcwService which analyses the transcript based on
    the assistant's acw_config: dispositions, resolution status,
    quality score, and summary (if enabled).
    """
    try:
        account_id = UUID(request.account_id)
        check_account_permission(user, str(account_id), "call_logs.delete", db)

        call_log = db.query(CallLog).filter(
            CallLog.id == call_log_id,
            CallLog.account_id == account_id
        ).first()

        if not call_log:
            raise HTTPException(status_code=404, detail="Call log not found")

        if not call_log.transcript:
            raise HTTPException(status_code=400, detail="No transcript available for this call")

        from ..services.acw_service import run_acw
        result = run_acw(call_log, db)

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        if result.get("skipped"):
            return {
                "success": False,
                "skipped": True,
                "reason": result.get("reason"),
            }

        disposition = result.get("disposition")
        return {
            "success": True,
            "summary": result.get("summary"),
            "disposition": disposition,
            "disposition_name": disposition.get("name") if disposition else None,
            "acw_resolution": result.get("acw_resolution"),
            "acw_quality_score": result.get("acw_quality_score"),
            "acw_completed_at": result.get("acw_completed_at"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error running post-call QA: {e}")
        raise HTTPException(status_code=500, detail="Failed to run post-call QA")


@router.patch("/{call_log_id}")
async def update_call_log(
    call_log_id: UUID,
    request: UpdateCallLogRequest,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a call log's disposition or summary."""
    check_account_permission(user, str(account_id), "call_logs.edit", db)
    try:
        call_log = db.query(CallLog).filter(
            CallLog.id == call_log_id,
            CallLog.account_id == account_id
        ).first()
        
        if not call_log:
            raise HTTPException(status_code=404, detail="Call log not found")
        
        if request.disposition_id is not None:
            if request.disposition_id == "":
                call_log.disposition_id = None
            else:
                disposition = db.query(AssistantDisposition).filter(
                    AssistantDisposition.id == UUID(request.disposition_id)
                ).first()
                if not disposition:
                    raise HTTPException(status_code=404, detail="Disposition not found")
                call_log.disposition_id = UUID(request.disposition_id)
        
        if request.ai_summary is not None:
            call_log.ai_summary = request.ai_summary

        if request.acw_resolution is not None:
            call_log.acw_resolution = request.acw_resolution if request.acw_resolution else None

        if request.acw_quality_score is not None:
            if not (0 <= request.acw_quality_score <= 100):
                raise HTTPException(status_code=400, detail="Quality score must be between 0 and 100")
            call_log.acw_quality_score = request.acw_quality_score

        db.commit()
        db.refresh(call_log)
        
        logger.info(f"Updated call log {call_log_id}")
        return call_log.to_dict(include_legs=True)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating call log: {e}")
        raise HTTPException(status_code=500, detail="Failed to update call log")


@router.delete("/{call_log_id}")
async def delete_call_log(
    call_log_id: UUID,
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a call log and its associated legs and events."""
    check_account_permission(user, str(account_id), "call_logs.delete", db)
    try:
        call_log = db.query(CallLog).filter(
            CallLog.id == call_log_id,
            CallLog.account_id == account_id,
        ).first()

        if not call_log:
            raise HTTPException(status_code=404, detail="Call log not found")

        db.delete(call_log)
        db.commit()
        logger.info(f"Deleted call log {call_log_id}")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting call log: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete call log")

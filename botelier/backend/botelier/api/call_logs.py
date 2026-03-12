"""
Call Logs API - CRUD operations for call history.

SECURITY: All endpoints enforce hotel_id filtering to prevent cross-tenant data access.
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
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import Session, joinedload
from loguru import logger

from botelier.database import get_db
from botelier.models import CallLog, CallLeg, CallStatus, Assistant, PhoneNumber, AssistantDisposition


router = APIRouter(prefix="/api/call-logs", tags=["Call Logs"])


@router.get("")
async def get_call_logs(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by call status"),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    phone_number_id: Optional[UUID] = Query(None, description="Filter by phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter calls from this date"),
    date_to: Optional[datetime] = Query(None, description="Filter calls until this date"),
    search: Optional[str] = Query(None, description="Search caller number or transcript"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    Get paginated call logs for a hotel.
    
    SECURITY: Filters by hotel_id to ensure tenant isolation.
    """
    try:
        query = db.query(CallLog).filter(CallLog.hotel_id == hotel_id)
        
        if status:
            query = query.filter(CallLog.status == status)
        
        if assistant_id:
            query = query.filter(CallLog.assistant_id == assistant_id)
        
        if phone_number_id:
            query = query.filter(CallLog.phone_number_id == phone_number_id)
        
        if date_from:
            query = query.filter(CallLog.started_at >= date_from)
        
        if date_to:
            query = query.filter(CallLog.started_at <= date_to)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    CallLog.caller_number.ilike(search_pattern),
                    CallLog.transcript.cast(str).ilike(search_pattern),
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
                Assistant.hotel_id == hotel_id
            ).all()
            assistants = {str(a.id): a.name for a in assistant_records}
        
        phone_numbers = {}
        if phone_ids:
            phone_records = db.query(PhoneNumber).filter(
                PhoneNumber.id.in_(phone_ids),
                PhoneNumber.hotel_id == hotel_id
            ).all()
            phone_numbers = {str(p.id): p.phone_number for p in phone_records}
        
        logs_with_names = []
        for log in call_logs:
            log_dict = log.to_dict(include_legs=True, include_transcript=True)
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
        
    except Exception as e:
        logger.exception(f"Error fetching call logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch call logs")


@router.get("/stats")
async def get_call_stats(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    db: Session = Depends(get_db),
):
    """
    Get call statistics for quick summary display.
    """
    try:
        since = datetime.utcnow() - timedelta(days=days)
        
        base_query = db.query(CallLog).filter(
            CallLog.hotel_id == hotel_id,
            CallLog.started_at >= since
        )
        
        total_calls = base_query.count()
        completed_calls = base_query.filter(CallLog.status == CallStatus.COMPLETED.value).count()
        transferred_calls = base_query.filter(CallLog.has_transfer == True).count()
        
        total_duration = db.query(func.sum(CallLog.duration_seconds)).filter(
            CallLog.hotel_id == hotel_id,
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
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    status: Optional[str] = Query(None),
    assistant_id: Optional[UUID] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Export call logs as CSV file.
    
    SECURITY: Filters by hotel_id to ensure tenant isolation.
    """
    try:
        query = db.query(CallLog).filter(CallLog.hotel_id == hotel_id)
        
        if status:
            query = query.filter(CallLog.status == status)
        if assistant_id:
            query = query.filter(CallLog.assistant_id == assistant_id)
        if date_from:
            query = query.filter(CallLog.started_at >= date_from)
        if date_to:
            query = query.filter(CallLog.started_at <= date_to)
        
        call_logs = query.options(joinedload(CallLog.legs)).order_by(desc(CallLog.started_at)).all()
        
        assistant_ids = list(set([log.assistant_id for log in call_logs if log.assistant_id]))
        assistants = {}
        if assistant_ids:
            records = db.query(Assistant).filter(
                Assistant.id.in_(assistant_ids),
                Assistant.hotel_id == hotel_id
            ).all()
            assistants = {str(a.id): a.name for a in records}
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Date/Time",
            "Duration (seconds)",
            "Caller",
            "To Number",
            "Assistant",
            "Status",
            "Outcome",
            "Has Transfer",
            "Leg Count",
            "Total Leg Duration",
        ])
        
        for log in call_logs:
            leg_count = len(log.legs) if log.legs else 0
            total_leg_duration = sum(leg.duration_seconds or 0 for leg in log.legs) if log.legs else 0
            
            writer.writerow([
                log.started_at.isoformat() if log.started_at else "",
                log.duration_seconds or 0,
                log.caller_number or "",
                log.to_number or "",
                assistants.get(str(log.assistant_id), "") if log.assistant_id else "",
                log.status or "",
                log.outcome or "",
                "Yes" if log.has_transfer else "No",
                leg_count,
                total_leg_duration,
            ])
        
        output.seek(0)
        
        filename = f"call_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.exception(f"Error exporting call logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to export call logs")


@router.get("/{call_log_id}")
async def get_call_log(
    call_log_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """
    Get a single call log with full details including transcript and legs.
    
    SECURITY: Validates hotel_id ownership to prevent unauthorized access.
    """
    try:
        call_log = (
            db.query(CallLog)
            .options(joinedload(CallLog.legs), joinedload(CallLog.disposition))
            .filter(
                CallLog.id == call_log_id,
                CallLog.hotel_id == hotel_id
            )
            .first()
        )
        
        if not call_log:
            raise HTTPException(status_code=404, detail="Call log not found")
        
        result = call_log.to_dict(include_legs=True, include_transcript=True)
        
        if call_log.assistant_id:
            assistant = db.query(Assistant).filter(
                Assistant.id == call_log.assistant_id,
                Assistant.hotel_id == hotel_id
            ).first()
            result["assistant_name"] = assistant.name if assistant else None
        
        if call_log.phone_number_id:
            phone = db.query(PhoneNumber).filter(
                PhoneNumber.id == call_log.phone_number_id,
                PhoneNumber.hotel_id == hotel_id
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
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """
    Get available filter options (assistants, phone numbers, statuses).
    
    Used to populate filter dropdowns in the UI.
    """
    try:
        assistants = db.query(Assistant).filter(
            Assistant.hotel_id == hotel_id
        ).order_by(Assistant.name).all()
        
        phone_numbers = db.query(PhoneNumber).filter(
            PhoneNumber.hotel_id == hotel_id
        ).order_by(PhoneNumber.phone_number).all()
        
        statuses = [status.value for status in CallStatus]
        
        return {
            "assistants": [{"id": str(a.id), "name": a.name} for a in assistants],
            "phone_numbers": [
                {"id": str(p.id), "number": p.phone_number, "name": p.friendly_name}
                for p in phone_numbers
            ],
            "statuses": statuses,
        }
        
    except Exception as e:
        logger.exception(f"Error fetching filter options: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch filter options")


class GenerateSummaryRequest(BaseModel):
    hotel_id: str


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
):
    """
    Run Post Call QA on a call transcript.

    Delegates to AcwService which analyses the transcript based on
    the assistant's acw_config: dispositions, resolution status,
    quality score, and summary (if enabled).
    """
    try:
        hotel_id = UUID(request.hotel_id)

        call_log = db.query(CallLog).filter(
            CallLog.id == call_log_id,
            CallLog.hotel_id == hotel_id
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
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """
    Update a call log's disposition or summary.
    
    Allows manual override of AI-selected disposition or summary edits.
    """
    try:
        call_log = db.query(CallLog).filter(
            CallLog.id == call_log_id,
            CallLog.hotel_id == hotel_id
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

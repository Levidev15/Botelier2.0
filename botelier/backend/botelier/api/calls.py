"""
Calls API - Handles Twilio webhook for incoming phone calls.

This module provides HTTP endpoints that Twilio calls when a phone number
receives an incoming call. It returns TwiML to start a Media Stream.

Also handles call status updates and creates call log records for analytics.
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from loguru import logger

from ..config.domain import get_websocket_url, get_public_base_url
from ..database import get_db
from ..models import CallLog, CallLeg, PhoneNumber, CallStatus, LegType
from ..models.call_event import CallEvent
from ..services.call_logger import CallLogger
from ..services.acw_service import run_acw_background


router = APIRouter(prefix="/api/calls", tags=["Calls"])


def _get_call_handler():
    """Lazy import to avoid circular dependencies"""
    from .websockets import call_handler
    return call_handler


def _event_exists(db: Session, call_log_id, event_type: str) -> bool:
    """
    Return True if a call event of the given type already exists for this call.

    Used to prevent duplicate events when both the pipeline path and the Twilio
    webhook path could write the same event type (e.g. call_answered is written
    by the pipeline at WebSocket connect and may also arrive via the Twilio
    in-progress status callback in production).
    """
    return (
        db.query(CallEvent)
        .filter(CallEvent.call_log_id == call_log_id, CallEvent.event_type == event_type)
        .first()
        is not None
    )


def _write_event(
    db: Session,
    call_log_id,
    event_type: str,
    event_source: str = "twilio",
    severity: str = "info",
    details: dict = None,
    call_started_at: datetime = None,
):
    """
    Write a call event directly to the database.

    Used for Twilio webhook events (call_initiated, call_answered, call_ended,
    transfer_connected, transfer_ended) which arrive via async HTTP handlers
    that are completely separate from the WebSocket pipeline — await here is safe.

    Non-fatal: errors are logged but never raised so the webhook response is
    always returned to Twilio.
    """
    try:
        now = datetime.utcnow()
        offset_ms = None
        if call_started_at:
            offset_ms = int((now - call_started_at).total_seconds() * 1000)

        event = CallEvent(
            id=uuid.uuid4(),
            call_log_id=call_log_id,
            event_type=event_type,
            event_source=event_source,
            severity=severity,
            occurred_at=now,
            offset_ms=offset_ms,
            details=details,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to write call event {event_type} for {call_log_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


@router.post("/incoming")
@router.get("/incoming")
async def incoming_call_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Twilio webhook for incoming phone calls.
    
    When a call comes in to a Botelier phone number, Twilio POSTs here.
    We return TwiML that tells Twilio to start a Media Stream to our WebSocket.
    
    Also creates a CallLog record for tracking.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        call_status = form_data.get("CallStatus", "")

        # Twilio sends status-callback POSTs to this same URL for terminal call states.
        # We must short-circuit here before spawning a WebSocket pipeline, otherwise
        # a completed/failed call would create a ghost Pipecat pipeline that idles for
        # 300 s before timing out.
        _TERMINAL_STATUSES = {"completed", "failed", "busy", "no-answer"}
        if call_status in _TERMINAL_STATUSES:
            logger.debug(f"incoming_call_webhook: skipping pipeline for terminal status '{call_status}' on {call_sid}")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
                media_type="application/xml",
            )
        
        logger.info(f"Incoming call webhook - CallSid: {call_sid}")
        logger.info(f"From: {from_number} → To: {to_number}, Status: {call_status}")
        
        phone_record = db.query(PhoneNumber).filter(
            PhoneNumber.phone_number == to_number
        ).first()
        
        call_log_id = None
        call_started_at = None

        if phone_record:
            existing_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            
            if not existing_log:
                now = datetime.utcnow()
                call_log = CallLog(
                    hotel_id=phone_record.hotel_id,
                    call_sid=call_sid,
                    phone_number_id=phone_record.id,
                    assistant_id=phone_record.assistant_id,
                    caller_number=from_number,
                    to_number=to_number,
                    status=CallStatus.INITIATED.value,
                    started_at=now,
                )
                db.add(call_log)
                db.flush()
                
                initial_leg = CallLeg(
                    call_log_id=call_log.id,
                    leg_number=1,
                    leg_type=LegType.AI_CONVERSATION.value,
                    call_sid=call_sid,
                    participant="AI Assistant",
                    participant_name=None,
                    status=CallStatus.INITIATED.value,
                    started_at=now,
                )
                db.add(initial_leg)
                
                db.commit()
                logger.info(f"Created call log for {call_sid}")
                call_log_id = call_log.id
                call_started_at = now
            else:
                call_log_id = existing_log.id
                call_started_at = existing_log.started_at
        else:
            logger.warning(f"No phone number record found for {to_number}")
        
        if call_log_id:
            _write_event(
                db,
                call_log_id=call_log_id,
                event_type="call_initiated",
                event_source="twilio",
                severity="info",
                details={"CallSid": call_sid, "From": from_number, "To": to_number, "CallStatus": call_status},
                call_started_at=call_started_at,
            )

        fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
        ws_url = get_websocket_url(path="/api/ws/call", fallback_host=fallback_host)
        
        base_url = get_public_base_url(fallback_host=fallback_host)
        status_callback_url = f"{base_url}/api/calls/status"
        
        logger.info(f"Directing call to WebSocket: {ws_url}")
        
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect action="{base_url}/api/calls/connect-complete">
        <Stream url="{ws_url}" statusCallback="{status_callback_url}" statusCallbackMethod="POST">
            <Parameter name="to" value="{to_number}" />
            <Parameter name="from" value="{from_number}" />
        </Stream>
    </Connect>
</Response>"""
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        logger.exception(f"Error handling incoming call webhook: {e}")
        
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>We're sorry, but we're unable to connect your call at this time. Please try again later.</Say>
    <Hangup/>
</Response>"""
        
        return Response(content=error_twiml, media_type="application/xml", status_code=500)


@router.post("/status")
async def call_status_callback(request: Request, db: Session = Depends(get_db)):
    """
    Twilio callback for call status updates.
    
    Twilio POSTs here when call status changes:
    - initiated, ringing, in-progress, completed, busy, failed, no-answer, canceled
    
    Uses CallLogger service to update the CallLog record.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        call_status = str(form_data.get("CallStatus", "")) if form_data.get("CallStatus") else None
        call_duration = form_data.get("CallDuration")
        parent_call_sid = str(form_data.get("ParentCallSid", "")) if form_data.get("ParentCallSid") else None
        to_number = str(form_data.get("To", "")) if form_data.get("To") else None
        
        logger.info(f"Call status update - SID: {call_sid}, Status: {call_status}, Duration: {call_duration}s")
        
        if not call_status:
            logger.debug("No CallStatus in callback, likely a stream status event")
            return {"status": "received"}
        
        call_logger = CallLogger(db)
        duration_seconds = int(call_duration) if call_duration else None
        
        if parent_call_sid:
            logger.info(f"Child call detected - Parent: {parent_call_sid}")
            call_logger.create_transfer_leg_from_callback(
                parent_call_sid=parent_call_sid,
                child_call_sid=call_sid,
                to_number=to_number or "",
                status=call_status
            )
            call_logger.update_leg_status(
                leg_call_sid=call_sid,
                status=call_status,
                duration_seconds=duration_seconds,
                parent_call_sid=parent_call_sid,
                to_number=to_number,
            )

            # Log transfer_connected / transfer_ended for parent call
            parent_log = call_logger.get_call_log(parent_call_sid)
            if parent_log:
                _TERMINAL = {"completed", "no-answer", "busy", "failed", "canceled"}
                if call_status == "in-progress":
                    _write_event(
                        db,
                        call_log_id=parent_log.id,
                        event_type="transfer_connected",
                        event_source="twilio",
                        severity="info",
                        details={"ChildCallSid": call_sid, "To": to_number},
                        call_started_at=parent_log.started_at,
                    )
                elif call_status in _TERMINAL:
                    _write_event(
                        db,
                        call_log_id=parent_log.id,
                        event_type="transfer_ended",
                        event_source="twilio",
                        severity="info",
                        details={"ChildCallSid": call_sid, "To": to_number, "CallStatus": call_status, "CallDuration": call_duration},
                        call_started_at=parent_log.started_at,
                    )
        else:
            call_logger.update_status(call_sid, call_status, duration_seconds)
            if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                call_logger.update_leg_status(
                    leg_call_sid=call_sid,
                    status=call_status,
                    duration_seconds=duration_seconds,
                )
                # Classify completed calls as ended_early when the AI greeting never played.
                # ai_greeting_completed is set directly from the pipeline the moment the
                # greeting TTS finishes — it is reliable regardless of Twilio webhook timing.
                if call_status == "completed":
                    _classify_log = call_logger.get_call_log(call_sid)
                    if _classify_log and not _classify_log.ai_greeting_completed:
                        _classify_log.status = CallStatus.ENDED_EARLY.value
                        _classify_log.ended_early = True
                        db.commit()

            # Log call_answered and call_ended events.
            # Both paths use _event_exists() to dedup:
            # - call_answered: pipeline writes it synchronously (with an immediate
            #   DB commit) at WebSocket stream connect; by the time Twilio's
            #   in-progress callback arrives the row is always visible.
            # - call_ended: connect-complete commits synchronously before Twilio's
            #   terminal status callback is delivered (seconds later).
            call_log = call_logger.get_call_log(call_sid)
            if call_log:
                _TERMINAL = {"completed", "busy", "failed", "no-answer", "canceled"}
                if call_status == "in-progress":
                    if not _event_exists(db, call_log.id, "call_answered"):
                        _write_event(
                            db,
                            call_log_id=call_log.id,
                            event_type="call_answered",
                            event_source="twilio",
                            severity="info",
                            details={"CallStatus": call_status},
                            call_started_at=call_log.started_at,
                        )
                elif call_status in _TERMINAL:
                    if not _event_exists(db, call_log.id, "call_ended"):
                        _write_event(
                            db,
                            call_log_id=call_log.id,
                            event_type="call_ended",
                            event_source="twilio",
                            severity="info" if call_status == "completed" else "warning",
                            details={"CallStatus": call_status, "CallDuration": call_duration},
                            call_started_at=call_log.started_at,
                        )
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling call status callback: {e}")
        return {"status": "error", "message": str(e)}


def _maybe_enqueue_acw(call_sid: str, db: Session, background_tasks: BackgroundTasks):
    call_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
    if not call_log or not call_log.assistant_id:
        return
    from ..models import Assistant
    assistant = db.query(Assistant).filter(Assistant.id == call_log.assistant_id).first()
    if not assistant:
        return
    acw_config = assistant.acw_config or {}
    if acw_config.get("auto_run"):
        logger.info(f"Enqueueing ACW background task for call {call_sid}")
        background_tasks.add_task(run_acw_background, call_log.id)


@router.post("/connect-complete")
@router.get("/connect-complete")
async def connect_complete(request: Request, db: Session = Depends(get_db), background_tasks: BackgroundTasks = BackgroundTasks()):
    """
    Called when <Connect> completes (Stream ends).
    
    This is the action URL for <Connect>, called when the media stream ends.
    We can return TwiML here to continue the call (e.g., for transfers).
    
    Uses CallLogger service for status updates and saves conversation transcript.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        
        logger.info(f"Connect complete - SID: {call_sid}")
        
        call_handler = _get_call_handler()
        await call_handler.save_transcript_for_call(call_sid)
        
        call_logger = CallLogger(db)
        
        if call_logger.has_transfer(call_sid):
            call_log = call_logger.get_call_log(call_sid)
            transfer_mode = call_log.transfer_mode if call_log else None
            
            if transfer_mode == "cold":
                # Cold (SIP REFER) transfer: Twilio already exited the bridge.
                # No /transfer-status callbacks will arrive — finalize the record now.
                call_logger.complete_cold_transfer(call_sid)
                logger.info(f"Cold transfer call {call_sid} finalized at connect-complete")
                _maybe_enqueue_acw(call_sid, db, background_tasks)
            else:
                # Warm transfer: Twilio is still bridging. Keep call alive and wait
                # for /transfer-status callbacks to arrive with the final duration.
                logger.info(f"Warm transfer call {call_sid} — keeping alive for status callbacks")
            
            return Response(content="", media_type="application/xml")
        
        call_logger.complete_call(call_sid)
        logger.info(f"Marked call {call_sid} as completed via connect-complete")

        # Log call_ended here for calls where Twilio's terminal status callback
        # is not reliably delivered (common in dev; also a safety net for prod).
        # Deduped so we never write a second event if Twilio's webhook arrived first.
        call_log = call_logger.get_call_log(call_sid)
        if call_log and not _event_exists(db, call_log.id, "call_ended"):
            _write_event(
                db,
                call_log_id=call_log.id,
                event_type="call_ended",
                event_source="pipecat",
                severity="info",
                details={"source": "connect_complete"},
                call_started_at=call_log.started_at,
            )

        _maybe_enqueue_acw(call_sid, db, background_tasks)
        
        hangup_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""
        
        return Response(content=hangup_twiml, media_type="application/xml")
        
    except Exception as e:
        logger.exception(f"Error in connect-complete: {e}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")


@router.post("/transfer-status")
async def transfer_status_callback(request: Request, db: Session = Depends(get_db), background_tasks: BackgroundTasks = BackgroundTasks()):
    """
    Callback specifically for tracking transfer call status.
    
    When a call is transferred using Twilio's update call API,
    this endpoint receives status updates for the transferred leg.
    
    Twilio sends these events: initiated, ringing, answered, completed
    This lets us track:
    - When the transfer started ringing
    - When it was answered (transfer leg duration starts)
    - When it ended (transfer leg duration ends)
    
    Uses CallLogger service to update leg status.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        call_status = str(form_data.get("CallStatus", "")) if form_data.get("CallStatus") else None
        call_duration = form_data.get("CallDuration")
        parent_call_sid = str(form_data.get("ParentCallSid", "")) if form_data.get("ParentCallSid") else None
        to_number = str(form_data.get("To", "")) if form_data.get("To") else None
        
        logger.info(f"Transfer status update - SID: {call_sid}, Parent: {parent_call_sid}, To: {to_number}, Status: {call_status}")
        
        if call_status:
            call_logger = CallLogger(db)
            duration_seconds = int(call_duration) if call_duration else None
            call_logger.update_leg_status(
                leg_call_sid=call_sid,
                status=call_status,
                duration_seconds=duration_seconds,
                parent_call_sid=parent_call_sid,
                to_number=to_number,
            )
            
            # Log transfer_connected / transfer_ended on parent call
            if parent_call_sid:
                parent_log = call_logger.get_call_log(parent_call_sid)
                if parent_log:
                    _TERMINAL = {"completed", "no-answer", "busy", "failed", "canceled"}
                    if call_status == "in-progress":
                        _write_event(
                            db,
                            call_log_id=parent_log.id,
                            event_type="transfer_connected",
                            event_source="twilio",
                            severity="info",
                            details={"ChildCallSid": call_sid, "To": to_number},
                            call_started_at=parent_log.started_at,
                        )
                    elif call_status in _TERMINAL:
                        _write_event(
                            db,
                            call_log_id=parent_log.id,
                            event_type="transfer_ended",
                            event_source="twilio",
                            severity="info",
                            details={"ChildCallSid": call_sid, "To": to_number, "CallStatus": call_status, "CallDuration": call_duration},
                            call_started_at=parent_log.started_at,
                        )

            _TERMINAL_TRANSFER_STATUSES = {"completed", "no-answer", "busy", "failed", "canceled"}
            if call_status in _TERMINAL_TRANSFER_STATUSES and parent_call_sid:
                logger.info(f"Transfer leg {call_sid} ended ({call_status}) — enqueueing ACW for parent call {parent_call_sid}")
                _maybe_enqueue_acw(parent_call_sid, db, background_tasks)
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling transfer status callback: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/{call_id}/events")
async def get_call_events(call_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Return the event timeline for a specific call.

    Events are ordered chronologically by occurred_at.

    Response items include:
        event_type, event_source, severity, offset_ms, occurred_at, details
    """
    from ..models.call_event import CallEvent as CallEventModel

    try:
        call_log = db.query(CallLog).filter(CallLog.id == call_id).first()
        if not call_log:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Call not found")

        events = (
            db.query(CallEventModel)
            .filter(CallEventModel.call_log_id == call_log.id)
            .order_by(CallEventModel.occurred_at)
            .all()
        )

        return [e.to_dict() for e in events]

    except Exception as e:
        logger.exception(f"Error fetching events for call {call_id}: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Internal server error")

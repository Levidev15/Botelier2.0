"""
Calls API - Handles Twilio webhook for incoming phone calls.

This module provides HTTP endpoints that Twilio calls when a phone number
receives an incoming call. It returns TwiML to start a Media Stream.

Also handles call status updates and creates call log records for analytics.
"""

from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy.orm import Session
from loguru import logger

from ..config.domain import get_websocket_url, get_public_base_url
from ..database import get_db
from ..models import CallLog, CallLeg, PhoneNumber, CallStatus, LegType
from ..services.call_logger import CallLogger


router = APIRouter(prefix="/api/calls", tags=["Calls"])


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
        call_status = form_data.get("CallStatus")
        
        logger.info(f"Incoming call webhook - CallSid: {call_sid}")
        logger.info(f"From: {from_number} → To: {to_number}, Status: {call_status}")
        
        phone_record = db.query(PhoneNumber).filter(
            PhoneNumber.phone_number == to_number
        ).first()
        
        if phone_record:
            existing_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            
            if not existing_log:
                call_log = CallLog(
                    hotel_id=phone_record.hotel_id,
                    call_sid=call_sid,
                    phone_number_id=phone_record.id,
                    assistant_id=phone_record.assistant_id,
                    caller_number=from_number,
                    to_number=to_number,
                    status=CallStatus.INITIATED.value,
                    started_at=datetime.utcnow(),
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
                    started_at=datetime.utcnow(),
                )
                db.add(initial_leg)
                
                db.commit()
                logger.info(f"Created call log for {call_sid}")
        else:
            logger.warning(f"No phone number record found for {to_number}")
        
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
            call_logger.update_leg_status(call_sid, call_status, duration_seconds)
        else:
            call_logger.update_status(call_sid, call_status, duration_seconds)
            if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                call_logger.update_leg_status(call_sid, call_status, duration_seconds)
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling call status callback: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/connect-complete")
@router.get("/connect-complete")
async def connect_complete(request: Request, db: Session = Depends(get_db)):
    """
    Called when <Connect> completes (Stream ends).
    
    This is the action URL for <Connect>, called when the media stream ends.
    We can return TwiML here to continue the call (e.g., for transfers).
    
    Uses CallLogger service for status updates.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        
        logger.info(f"Connect complete - SID: {call_sid}")
        
        call_logger = CallLogger(db)
        
        if call_logger.has_transfer(call_sid):
            logger.info(f"Call {call_sid} had transfer, not hanging up")
            return Response(content="", media_type="application/xml")
        
        call_logger.complete_call(call_sid)
        logger.info(f"Marked call {call_sid} as completed via connect-complete")
        
        hangup_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""
        
        return Response(content=hangup_twiml, media_type="application/xml")
        
    except Exception as e:
        logger.exception(f"Error in connect-complete: {e}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")


@router.post("/transfer-status")
async def transfer_status_callback(request: Request, db: Session = Depends(get_db)):
    """
    Callback specifically for tracking transfer call status.
    
    When a call is transferred using Twilio's update call API,
    this endpoint receives status updates for the transferred leg.
    
    Uses CallLogger service to update leg status.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        call_status = str(form_data.get("CallStatus", "")) if form_data.get("CallStatus") else None
        call_duration = form_data.get("CallDuration")
        parent_call_sid = str(form_data.get("ParentCallSid", "")) if form_data.get("ParentCallSid") else None
        
        logger.info(f"Transfer status update - SID: {call_sid}, Parent: {parent_call_sid}, Status: {call_status}")
        
        if call_status:
            call_logger = CallLogger(db)
            duration_seconds = int(call_duration) if call_duration else None
            call_logger.update_leg_status(call_sid, call_status, duration_seconds)
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling transfer status callback: {e}")
        return {"status": "error", "message": str(e)}

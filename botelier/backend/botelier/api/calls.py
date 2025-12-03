"""
Calls API - Handles Twilio webhook for incoming phone calls.

This module provides HTTP endpoints that Twilio calls when a phone number
receives an incoming call. It returns TwiML to start a Media Stream.

Also handles call status updates and creates call log records for analytics.
"""

import os
from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from loguru import logger

from ..config.domain import get_websocket_url
from ..database import get_db
from ..models import CallLog, CallLeg, PhoneNumber, CallStatus, LegType


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
        
        logger.info(f"Directing call to WebSocket: {ws_url}")
        
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
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
    
    Updates the CallLog record with the new status and duration.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        call_duration = form_data.get("CallDuration")
        parent_call_sid = form_data.get("ParentCallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        
        logger.info(f"Call status update - SID: {call_sid}, Status: {call_status}, Duration: {call_duration}s")
        
        if parent_call_sid:
            logger.info(f"Child call detected - Parent: {parent_call_sid}")
        
        call_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
        
        if not call_log and parent_call_sid:
            call_log = db.query(CallLog).filter(CallLog.call_sid == parent_call_sid).first()
            
            if call_log:
                existing_leg = db.query(CallLeg).filter(
                    CallLeg.call_log_id == call_log.id,
                    CallLeg.call_sid == call_sid
                ).first()
                
                if not existing_leg:
                    max_leg = db.query(CallLeg).filter(
                        CallLeg.call_log_id == call_log.id
                    ).order_by(CallLeg.leg_number.desc()).first()
                    
                    next_leg_num = (max_leg.leg_number + 1) if max_leg else 1
                    
                    transfer_leg = CallLeg(
                        call_log_id=call_log.id,
                        leg_number=next_leg_num,
                        leg_type=LegType.TRANSFER_EXTERNAL.value,
                        call_sid=call_sid,
                        participant=to_number,
                        participant_name=None,
                        status=call_status or CallStatus.INITIATED.value,
                        started_at=datetime.utcnow(),
                    )
                    db.add(transfer_leg)
                    
                    call_log.has_transfer = True
                    
                    logger.info(f"Created transfer leg {next_leg_num} for call {parent_call_sid}")
        
        if call_log:
            status_mapping = {
                "initiated": CallStatus.INITIATED.value,
                "ringing": CallStatus.RINGING.value,
                "in-progress": CallStatus.IN_PROGRESS.value,
                "completed": CallStatus.COMPLETED.value,
                "busy": CallStatus.BUSY.value,
                "failed": CallStatus.FAILED.value,
                "no-answer": CallStatus.NO_ANSWER.value,
                "canceled": CallStatus.CANCELED.value,
            }
            
            new_status = status_mapping.get(call_status, call_status)
            
            if not parent_call_sid:
                call_log.status = new_status
                
                if call_status == "in-progress" and not call_log.answered_at:
                    call_log.answered_at = datetime.utcnow()
                
                if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                    call_log.ended_at = datetime.utcnow()
                    if call_duration:
                        call_log.duration_seconds = int(call_duration)
            
            leg = db.query(CallLeg).filter(CallLeg.call_sid == call_sid).first()
            if leg:
                leg.status = new_status
                if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                    leg.ended_at = datetime.utcnow()
                    if call_duration:
                        leg.duration_seconds = int(call_duration)
            
            db.commit()
            logger.info(f"Updated call log {call_log.id} with status {new_status}")
        else:
            logger.warning(f"No call log found for SID: {call_sid}")
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling call status callback: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/transfer-status")
async def transfer_status_callback(request: Request, db: Session = Depends(get_db)):
    """
    Callback specifically for tracking transfer call status.
    
    When a call is transferred using Twilio's update call API,
    this endpoint receives status updates for the transferred leg.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        call_duration = form_data.get("CallDuration")
        parent_call_sid = form_data.get("ParentCallSid")
        
        logger.info(f"Transfer status update - SID: {call_sid}, Parent: {parent_call_sid}, Status: {call_status}")
        
        if parent_call_sid:
            call_log = db.query(CallLog).filter(CallLog.call_sid == parent_call_sid).first()
            
            if call_log:
                leg = db.query(CallLeg).filter(CallLeg.call_sid == call_sid).first()
                
                if leg:
                    leg.status = call_status
                    if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                        leg.ended_at = datetime.utcnow()
                        if call_duration:
                            leg.duration_seconds = int(call_duration)
                    db.commit()
                    logger.info(f"Updated transfer leg {leg.leg_number} with status {call_status}")
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling transfer status callback: {e}")
        return {"status": "error", "message": str(e)}

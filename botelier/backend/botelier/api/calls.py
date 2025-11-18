"""
Calls API - Handles Twilio webhook for incoming phone calls.

This module provides HTTP endpoints that Twilio calls when a phone number
receives an incoming call. It returns TwiML to start a Media Stream.
"""

import os
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
from loguru import logger

from ..config.domain import get_websocket_url


router = APIRouter(prefix="/api/calls", tags=["Calls"])


@router.post("/incoming")
@router.get("/incoming")  # Twilio may use GET for initial webhook verification
async def incoming_call_webhook(request: Request):
    """
    Twilio webhook for incoming phone calls.
    
    When a call comes in to a Botelier phone number, Twilio POSTs here.
    We return TwiML that tells Twilio to start a Media Stream to our WebSocket.
    
    TwiML Flow:
        1. <Connect> - Start connection
        2. <Stream> - Open WebSocket to /ws/call
        3. Audio flows: Caller ↔ Twilio ↔ WebSocket ↔ Pipecat
    
    Twilio sends form data:
        - CallSid: Unique call identifier
        - From: Caller's phone number
        - To: Botelier phone number
        - CallStatus: "ringing", "in-progress", etc.
    
    Returns:
        TwiML XML that starts Media Stream
    """
    try:
        # Parse Twilio's form data
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        from_number = form_data.get("From")
        to_number = form_data.get("To")
        call_status = form_data.get("CallStatus")
        
        logger.info(f"Incoming call webhook - CallSid: {call_sid}")
        logger.info(f"From: {from_number} → To: {to_number}, Status: {call_status}")
        
        # Get WebSocket URL using domain helper
        # This works in both Replit dev and production with custom domains
        fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
        ws_url = get_websocket_url(path="/ws/call", fallback_host=fallback_host)
        
        logger.info(f"Directing call to WebSocket: {ws_url}")
        
        # Return TwiML to start Media Stream
        # Pass phone numbers as URL query params so we can look up the assistant
        # before Pipecat starts processing the WebSocket
        ws_url_with_params = f"{ws_url}?from={from_number}&to={to_number}"
        
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url_with_params}" />
    </Connect>
</Response>"""
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        logger.exception(f"Error handling incoming call webhook: {e}")
        
        # Return error TwiML
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>We're sorry, but we're unable to connect your call at this time. Please try again later.</Say>
    <Hangup/>
</Response>"""
        
        return Response(content=error_twiml, media_type="application/xml", status_code=500)


@router.post("/status")
async def call_status_callback(request: Request):
    """
    Twilio callback for call status updates.
    
    Twilio POSTs here when call status changes:
    - initiated
    - ringing
    - answered
    - completed
    
    This is useful for logging and analytics.
    """
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        call_duration = form_data.get("CallDuration")
        
        logger.info(f"Call status update - SID: {call_sid}, Status: {call_status}, Duration: {call_duration}s")
        
        # TODO: Store call records in database for analytics
        # - Call start/end times
        # - Duration
        # - Assistant used
        # - Caller information
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling call status callback: {e}")
        return {"status": "error", "message": str(e)}

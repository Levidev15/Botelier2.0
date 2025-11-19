"""
WebSocket API - Handles Twilio Media Streams connections.

This module provides WebSocket endpoints for real-time audio streaming
between Twilio and Pipecat voice pipelines.
"""

import json
from urllib.parse import parse_qs, urlparse
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Request
from sqlalchemy.orm import Session
from loguru import logger

from ..database import get_db
from ..voice.call_handler import CallHandler


router = APIRouter(prefix="/api/ws", tags=["WebSocket"])


@router.websocket("/call")
async def websocket_call_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Twilio Media Streams - Official Pipecat Pattern.
    
    Twilio sends: 'connected' → 'start' (with stream_sid) → 'media' frames
    
    Pattern:
        1. Accept WebSocket
        2. Read 'start' event to get stream_sid/call_sid
        3. Look up assistant by phone number (from 'start' event or query param)
        4. Create Pipecat pipeline with FastAPIWebsocketTransport
        5. Run pipeline (Pipecat handles all subsequent Twilio messages)
    
    URL: wss://domain/api/ws/call?to=%2B17027074036
    """
    try:
        # Step 1: Accept WebSocket (Pipecat official pattern)
        await websocket.accept()
        logger.info("✅ WebSocket accepted, waiting for Twilio 'start' event")
        
        # Step 2: Read Twilio 'start' event to get stream_sid/call_sid
        # This is REQUIRED before creating TwilioFrameSerializer
        stream_sid = None
        call_sid = None
        to_number = None
        start_data = {}
        
        # Read initial messages from Twilio
        for _ in range(3):  # Twilio sends 'connected' then 'start'
            data = await websocket.receive_text()
            message = json.loads(data)
            event_type = message.get("event")
            
            if event_type == "start":
                start_data = message.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid")
                # Extract phone number from TwiML <Parameter> tags (official Pipecat pattern)
                custom_params = start_data.get("customParameters", {})
                to_number = custom_params.get("to")
                from_number = custom_params.get("from")
                logger.info(f"📞 Call started - Stream: {stream_sid}, Call: {call_sid}")
                logger.info(f"📞 From: {from_number} → To: {to_number}")
                break
        
        if not stream_sid or not call_sid:
            logger.error("❌ Never received Twilio 'start' event")
            await websocket.close()
            return
        
        if not to_number:
            logger.error(f"❌ Missing 'to' in customParameters. Start data: {start_data}")
            await websocket.close(code=1008, reason="Missing phone number")
            return
        
        # Check for duplicate call EARLY (before delegating to handler)
        # This prevents both connections from processing Twilio messages
        from ..voice.call_handler import CallHandler
        async with CallHandler._lock:
            if call_sid in CallHandler._active_calls:
                logger.warning(f"⚠️ Duplicate WebSocket for call {call_sid}, rejecting early")
                await websocket.close(code=1000, reason="Duplicate connection")
                return
            # Reserve this call_sid immediately
            CallHandler._active_calls[call_sid] = None
        
        logger.info(f"🔌 Handling call for phone: {to_number}")
        
        # Step 3-5: Delegate to CallHandler (Pipecat pattern)
        handler = CallHandler()
        try:
            await handler.handle_call(
                websocket=websocket,
                to_number=to_number,
                stream_sid=stream_sid,
                call_sid=call_sid,
                db=db
            )
        finally:
            # Cleanup on exit
            if call_sid in CallHandler._active_calls:
                del CallHandler._active_calls[call_sid]
        
    except Exception as e:
        logger.exception(f"❌ WebSocket error: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

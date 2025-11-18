"""
WebSocket API - Handles Twilio Media Streams connections.

This module provides WebSocket endpoints for real-time audio streaming
between Twilio and Pipecat voice pipelines.
"""

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from loguru import logger

from ..database import get_db
from ..voice.call_handler import CallHandler


router = APIRouter(prefix="/ws", tags=["WebSocket"])


@router.websocket("/call")
async def websocket_call_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Twilio Media Streams.
    
    Twilio connects here after the HTTP webhook returns TwiML with <Stream>.
    
    Flow:
        1. Accept WebSocket connection
        2. Wait for Twilio 'start' event with call metadata
        3. Extract stream_sid, call_sid, from, to
        4. Hand off to CallHandler for pipeline orchestration
        5. Stream audio until call ends
    
    Twilio sends JSON events:
        - "start": Call metadata (stream_sid, call_sid, from, to, etc.)
        - "media": Audio payload (base64 μ-law)
        - "stop": Call ended
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted from Twilio")
    
    # Wait for Twilio's 'start' event with call metadata
    stream_sid = None
    call_sid = None
    from_number = None
    to_number = None
    
    try:
        # First message from Twilio is always the 'start' event
        data = await websocket.receive_text()
        message = json.loads(data)
        
        if message.get("event") == "start":
            start_data = message.get("start", {})
            stream_sid = message.get("streamSid")
            call_sid = start_data.get("callSid")
            from_number = start_data.get("customParameters", {}).get("from") or start_data.get("from")
            to_number = start_data.get("customParameters", {}).get("to") or start_data.get("to")
            
            logger.info(f"Twilio call started - Stream: {stream_sid}, Call: {call_sid}")
            logger.info(f"From: {from_number} → To: {to_number}")
            
            # Validate required fields
            if not all([stream_sid, call_sid, to_number]):
                logger.error(f"Missing required fields - stream_sid: {stream_sid}, call_sid: {call_sid}, to_number: {to_number}")
                await websocket.close()
                return
            
            # Create call handler and process the call
            handler = CallHandler(db)
            await handler.handle_call(
                websocket=websocket,
                stream_sid=stream_sid,
                call_sid=call_sid,
                from_number=from_number or "Unknown",
                to_number=to_number,
            )
        else:
            logger.warning(f"Expected 'start' event, got: {message.get('event')}")
            await websocket.close()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call {call_sid}")
    except Exception as e:
        logger.exception(f"Error in WebSocket endpoint: {e}")
        try:
            await websocket.close()
        except:
            pass

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
    from_number: str = "",  # From URL query params
    to: str = "",  # To phone number from URL query params
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Twilio Media Streams.
    
    Twilio connects here after the HTTP webhook returns TwiML with <Stream>.
    
    IMPORTANT: This endpoint does NOT manually parse Twilio WebSocket events!
    Pipecat's FastAPIWebsocketTransport + TwilioFrameSerializer handle the entire
    Twilio protocol automatically (start, media, stop events).
    
    Flow:
        1. Extract phone numbers from URL query params (from TwiML)
        2. Look up which assistant is assigned to the phone number
        3. Create Pipecat pipeline with assistant config
        4. Let Pipecat's transport handle the entire WebSocket lifecycle
    
    URL format: wss://domain/ws/call?from=+1234567890&to=+0987654321
    """
    logger.info(f"WebSocket connection from Twilio - From: {from_number} → To: {to}")
    
    try:
        # Validate phone number
        if not to:
            logger.error("Missing 'to' phone number in query params")
            await websocket.close(code=1008, reason="Missing phone number")
            return
        
        # Create call handler and let it orchestrate the Pipecat pipeline
        # The handler will create the transport which handles websocket.accept() and all Twilio events
        handler = CallHandler(db)
        await handler.handle_call(
            websocket=websocket,
            from_number=from_number or "Unknown",
            to_number=to,
        )
        
    except Exception as e:
        logger.exception(f"Error in WebSocket endpoint: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

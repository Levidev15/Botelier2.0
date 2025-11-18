"""
WebSocket API - Handles Twilio Media Streams connections.

This module provides WebSocket endpoints for real-time audio streaming
between Twilio and Pipecat voice pipelines.
"""

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
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
    WebSocket endpoint for Twilio Media Streams.
    
    Twilio connects here after the HTTP webhook returns TwiML with <Stream>.
    
    Architecture:
        - Pipecat's TwilioFrameSerializer IGNORES 'start' events (returns None)
        - stream_sid is REQUIRED in serializer constructor (not Optional)
        - Therefore, we MUST manually parse 'start' to bootstrap the serializer
        - This is the correct integration pattern per Pipecat's design
    
    Flow:
        1. Extract phone numbers from URL query params (from TwiML)
        2. Pass to CallHandler which:
           a. Accepts WebSocket
           b. Receives 'start' event to get stream_sid/call_sid
           c. Creates TwilioFrameSerializer with those IDs
           d. Creates FastAPIWebsocketTransport
           e. Lets Pipecat handle all subsequent messages (media, dtmf, stop)
    
    URL format: wss://domain/api/ws/call (phone numbers in <Parameter> tags)
    """
    # Log WebSocket endpoint hit for debugging
    logger.info(f"🔌 WebSocket endpoint /api/ws/call hit!")
    logger.info(f"WebSocket state: {websocket.client_state}")
    
    try:
        # Create call handler - it will accept WebSocket, read parameters from Twilio 'start' event,
        # and orchestrate Pipecat pipeline
        handler = CallHandler(db)
        await handler.handle_call(websocket=websocket)
        
    except Exception as e:
        logger.exception(f"Error in WebSocket endpoint: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

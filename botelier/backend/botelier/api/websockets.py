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
    
    Flow:
        1. Accept WebSocket first (required for FastAPI WebSocket)
        2. Extract phone number from query params or Twilio 'start' event
        3. Look up assistant assigned to phone number
        4. Create Pipecat pipeline and run
    
    URL format: wss://domain/api/ws/call?to=%2B17027074036
    """
    try:
        # Extract phone number from query params
        # Access directly from websocket.query_params (available after accept)
        to_number = websocket.query_params.get("to")
        
        if not to_number:
            logger.error("❌ Missing 'to' query parameter")
            await websocket.accept()
            await websocket.close(code=1008, reason="Missing 'to' parameter")
            return
        
        logger.info(f"🔌 WebSocket connection for phone number: {to_number}")
        
        handler = CallHandler()
        await handler.handle_call(websocket=websocket, to_number=to_number, db=db)
        
    except Exception as e:
        logger.exception(f"Error in WebSocket endpoint: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

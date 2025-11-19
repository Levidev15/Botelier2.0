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
    to: str = Query(..., description="Phone number being called (Botelier number)"),
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Twilio Media Streams.
    
    Twilio connects here after the HTTP webhook returns TwiML with <Stream>.
    
    Flow:
        1. Extract phone number from query params
        2. Look up assistant assigned to phone number
        3. Create Pipecat pipeline (FastAPIWebsocketTransport handles WebSocket internally)
        4. Run pipeline (blocking until call ends)
    
    URL format: wss://domain/api/ws/call?to=%2B17027074036
    """
    logger.info(f"🔌 WebSocket connection for phone number: {to}")
    
    try:
        handler = CallHandler()
        await handler.handle_call(websocket=websocket, to_number=to, db=db)
        
    except Exception as e:
        logger.exception(f"Error in WebSocket endpoint: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

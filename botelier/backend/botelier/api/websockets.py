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
    WebSocket endpoint for Twilio Media Streams.
    
    Twilio connects here after the HTTP webhook returns TwiML with <Stream>.
    
    Flow:
        1. Extract phone number from WebSocket URL query params
        2. Accept WebSocket
        3. Look up assistant and create Pipecat pipeline
    
    URL format: wss://domain/api/ws/call?to=%2B17027074036
    """
    try:
        # Extract query params from WebSocket URL (before accept)
        # websocket.url is a Starlette URL object with query params
        to_number = websocket.url.query.get("to") if hasattr(websocket.url, 'query') else None
        
        # Fallback: parse from scope
        if not to_number and websocket.scope.get("query_string"):
            query_string = websocket.scope["query_string"].decode()
            params = parse_qs(query_string)
            to_number = params.get("to", [None])[0]
        
        if not to_number:
            logger.error(f"❌ Missing 'to' query parameter. URL: {websocket.url}")
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

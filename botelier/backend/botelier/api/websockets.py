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
from ..models import CallLog
from ..voice.call_handler import CallHandler
from ._twilio_auth import get_call_auth_token, verify_stream_token


router = APIRouter(prefix="/api/ws", tags=["WebSocket"])

# Module-level CallHandler instance persists across WebSocket connections
# This ensures FlowExecutor state is maintained during multi-turn conversations
call_handler = CallHandler()


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

        # --- Stream authenticity (Task #138) ---
        # Twilio Media Streams cannot carry an X-Twilio-Signature header
        # on the WebSocket upgrade. Instead, /api/calls/incoming mints a
        # short-lived HMAC token bound to (CallSid, To) and embeds it in
        # TwiML <Parameter> tags. Verify it here BEFORE we hand the
        # connection to CallHandler so a forged 'start' frame cannot
        # drive the assistant pipeline, tools, or transfers.
        custom_params = start_data.get("customParameters", {}) or {}
        stream_token = str(custom_params.get("streamToken", "") or "")
        stream_token_exp = custom_params.get("streamTokenExp", "")

        # Bind the WebSocket to a CallLog row that was created by a
        # signature-validated /api/calls/incoming. If no such row exists,
        # the supplied call_sid was never blessed by Twilio — refuse.
        call_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
        if call_log is None:
            logger.warning(
                f"❌ Rejecting /api/ws/call: no CallLog for call_sid={call_sid} "
                f"(forged start frame or unblessed CallSid)"
            )
            await websocket.close(code=1008, reason="Unknown call")
            return

        # Tightness invariant: the (CallSid, To) pair the WS claims must
        # match the (CallSid, To) pair recorded by the validated /incoming.
        # Stops an attacker who knows a real CallSid from re-pointing the
        # stream at a different tenant's `to_number`.
        if call_log.to_number and call_log.to_number != to_number:
            logger.warning(
                f"❌ Rejecting /api/ws/call: to_number mismatch for call_sid={call_sid} "
                f"(claimed={to_number} expected={call_log.to_number})"
            )
            await websocket.close(code=1008, reason="Call binding mismatch")
            return

        # Resolve the per-account auth token used as the HMAC secret.
        # When no secret is configured anywhere (local dev), the verifier
        # returns (True, "skipped_no_secret"). The CallLog binding above
        # is still enforced, so dev parity is preserved.
        account_token = get_call_auth_token(
            db, to_number=to_number, call_sid=call_sid
        )
        token_ok, token_reason = verify_stream_token(
            call_sid=call_sid,
            to_number=to_number,
            token=stream_token,
            exp=stream_token_exp,
            account_token=account_token,
        )
        if not token_ok:
            logger.warning(
                f"❌ Rejecting /api/ws/call: stream token {token_reason} "
                f"for call_sid={call_sid} to={to_number}"
            )
            await websocket.close(code=1008, reason="Invalid stream token")
            return

        logger.info(f"🔌 Handling call for phone: {to_number}")
        
        # Step 3-5: Delegate to CallHandler
        # Use module-level instance to persist state across function calls
        await call_handler.handle_call(
            websocket=websocket,
            to_number=to_number,
            stream_sid=stream_sid,
            call_sid=call_sid,
            db=db,
            from_number=from_number,
        )
        
    except Exception as e:
        logger.exception(f"❌ WebSocket error: {e}")
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        except:
            pass

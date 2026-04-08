"""
Calls API - Handles Twilio webhook for incoming phone calls.

This module provides HTTP endpoints that Twilio calls when a phone number
receives an incoming call. It returns TwiML to start a Media Stream.

Also handles call status updates and creates call log records for analytics.
"""

import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from loguru import logger

from ..config.domain import get_websocket_url, get_public_base_url
from ..database import get_db
from ..models import CallLog, CallLeg, PhoneNumber, CallStatus, LegType
from ..models.call_event import CallEvent
from ..models.user import User
from ..services.call_logger import CallLogger
from ..services.acw_service import run_acw_background
from ..auth.middleware import get_current_user, check_account_permission


router = APIRouter(prefix="/api/calls", tags=["Calls"])


def _get_call_handler():
    """Lazy import to avoid circular dependencies"""
    from .websockets import call_handler
    return call_handler


def _event_exists(db: Session, call_log_id, event_type: str) -> bool:
    """
    Return True if a call event of the given type already exists for this call.

    Used to prevent duplicate events when both the pipeline path and the Twilio
    webhook path could write the same event type (e.g. call_answered is written
    by the pipeline at WebSocket connect and may also arrive via the Twilio
    in-progress status callback in production).
    """
    return (
        db.query(CallEvent)
        .filter(CallEvent.call_log_id == call_log_id, CallEvent.event_type == event_type)
        .first()
        is not None
    )


def _write_event(
    db: Session,
    call_log_id,
    event_type: str,
    event_source: str = "twilio",
    severity: str = "info",
    details: dict = None,
    call_started_at: datetime = None,
):
    """
    Write a call event directly to the database.

    Used for Twilio webhook events (call_initiated, call_answered, call_ended,
    transfer_connected, transfer_ended) which arrive via async HTTP handlers
    that are completely separate from the WebSocket pipeline — await here is safe.

    Non-fatal: errors are logged but never raised so the webhook response is
    always returned to Twilio.
    """
    try:
        now = datetime.utcnow()
        offset_ms = None
        if call_started_at:
            offset_ms = int((now - call_started_at).total_seconds() * 1000)

        event = CallEvent(
            id=uuid.uuid4(),
            call_log_id=call_log_id,
            event_type=event_type,
            event_source=event_source,
            severity=severity,
            occurred_at=now,
            offset_ms=offset_ms,
            details=details,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to write call event {event_type} for {call_log_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


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
        call_status = form_data.get("CallStatus", "")

        # Twilio sends status-callback POSTs to this same URL for terminal call states.
        # We must short-circuit here before spawning a WebSocket pipeline, otherwise
        # a completed/failed call would create a ghost Pipecat pipeline that idles for
        # 300 s before timing out.
        _TERMINAL_STATUSES = {"completed", "failed", "busy", "no-answer"}
        if call_status in _TERMINAL_STATUSES:
            logger.debug(f"incoming_call_webhook: skipping pipeline for terminal status '{call_status}' on {call_sid}")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
                media_type="application/xml",
            )
        
        logger.info(f"Incoming call webhook - CallSid: {call_sid}")
        logger.info(f"From: {from_number} → To: {to_number}, Status: {call_status}")
        
        phone_record = db.query(PhoneNumber).filter(
            PhoneNumber.phone_number == to_number
        ).first()
        
        call_log_id = None
        call_started_at = None

        if phone_record:
            existing_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            
            if not existing_log:
                now = datetime.utcnow()
                call_log = CallLog(
                    hotel_id=phone_record.hotel_id,
                    call_sid=call_sid,
                    phone_number_id=phone_record.id,
                    assistant_id=phone_record.assistant_id,
                    caller_number=from_number,
                    to_number=to_number,
                    status=CallStatus.INITIATED.value,
                    started_at=now,
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
                    started_at=now,
                )
                db.add(initial_leg)
                
                db.commit()
                logger.info(f"Created call log for {call_sid}")
                call_log_id = call_log.id
                call_started_at = now
            else:
                call_log_id = existing_log.id
                call_started_at = existing_log.started_at
        else:
            logger.warning(f"No phone number record found for {to_number}")
        
        if call_log_id:
            _write_event(
                db,
                call_log_id=call_log_id,
                event_type="call_initiated",
                event_source="twilio",
                severity="info",
                details={"CallSid": call_sid, "From": from_number, "To": to_number, "CallStatus": call_status},
                call_started_at=call_started_at,
            )

        fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
        ws_url = get_websocket_url(path="/api/ws/call", fallback_host=fallback_host)
        
        base_url = get_public_base_url(fallback_host=fallback_host)
        status_callback_url = f"{base_url}/api/calls/status"
        
        logger.info(f"Directing call to WebSocket: {ws_url}")
        
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect action="{base_url}/api/calls/connect-complete">
        <Stream url="{ws_url}" statusCallback="{status_callback_url}" statusCallbackMethod="POST">
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
    
    Uses CallLogger service to update the CallLog record.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        call_status = str(form_data.get("CallStatus", "")) if form_data.get("CallStatus") else None
        call_duration = form_data.get("CallDuration")
        parent_call_sid = str(form_data.get("ParentCallSid", "")) if form_data.get("ParentCallSid") else None
        to_number = str(form_data.get("To", "")) if form_data.get("To") else None
        
        logger.info(f"Call status update - SID: {call_sid}, Status: {call_status}, Duration: {call_duration}s")
        
        if not call_status:
            logger.debug("No CallStatus in callback, likely a stream status event")
            return {"status": "received"}
        
        call_logger = CallLogger(db)
        duration_seconds = int(call_duration) if call_duration else None
        
        if parent_call_sid:
            logger.info(f"Child call detected - Parent: {parent_call_sid}")
            call_logger.create_transfer_leg_from_callback(
                parent_call_sid=parent_call_sid,
                child_call_sid=call_sid,
                to_number=to_number or "",
                status=call_status
            )
            call_logger.update_leg_status(
                leg_call_sid=call_sid,
                status=call_status,
                duration_seconds=duration_seconds,
                parent_call_sid=parent_call_sid,
                to_number=to_number,
            )

            # Log transfer_connected / transfer_ended for parent call
            parent_log = call_logger.get_call_log(parent_call_sid)
            if parent_log:
                _TERMINAL = {"completed", "no-answer", "busy", "failed", "canceled"}
                if call_status == "in-progress":
                    _write_event(
                        db,
                        call_log_id=parent_log.id,
                        event_type="transfer_connected",
                        event_source="twilio",
                        severity="info",
                        details={"ChildCallSid": call_sid, "To": to_number},
                        call_started_at=parent_log.started_at,
                    )
                elif call_status in _TERMINAL:
                    _write_event(
                        db,
                        call_log_id=parent_log.id,
                        event_type="transfer_ended",
                        event_source="twilio",
                        severity="info",
                        details={"ChildCallSid": call_sid, "To": to_number, "CallStatus": call_status, "CallDuration": call_duration},
                        call_started_at=parent_log.started_at,
                    )
        else:
            call_logger.update_status(call_sid, call_status, duration_seconds)
            if call_status in ("completed", "busy", "failed", "no-answer", "canceled"):
                call_logger.update_leg_status(
                    leg_call_sid=call_sid,
                    status=call_status,
                    duration_seconds=duration_seconds,
                )
                # Classify completed calls as ended_early when the AI greeting never played.
                # ai_greeting_completed is set directly from the pipeline the moment the
                # greeting TTS finishes — it is reliable regardless of Twilio webhook timing.
                if call_status == "completed":
                    _classify_log = call_logger.get_call_log(call_sid)
                    if _classify_log and not _classify_log.ai_greeting_completed:
                        _classify_log.status = CallStatus.ENDED_EARLY.value
                        _classify_log.ended_early = True
                        db.commit()

            # Log call_answered and call_ended events.
            # Both paths use _event_exists() to dedup:
            # - call_answered: pipeline writes it synchronously (with an immediate
            #   DB commit) at WebSocket stream connect; by the time Twilio's
            #   in-progress callback arrives the row is always visible.
            # - call_ended: connect-complete commits synchronously before Twilio's
            #   terminal status callback is delivered (seconds later).
            call_log = call_logger.get_call_log(call_sid)
            if call_log:
                _TERMINAL = {"completed", "busy", "failed", "no-answer", "canceled"}
                if call_status == "in-progress":
                    if not _event_exists(db, call_log.id, "call_answered"):
                        _write_event(
                            db,
                            call_log_id=call_log.id,
                            event_type="call_answered",
                            event_source="twilio",
                            severity="info",
                            details={"CallStatus": call_status},
                            call_started_at=call_log.started_at,
                        )
                elif call_status in _TERMINAL:
                    if not _event_exists(db, call_log.id, "call_ended"):
                        _write_event(
                            db,
                            call_log_id=call_log.id,
                            event_type="call_ended",
                            event_source="twilio",
                            severity="info" if call_status == "completed" else "warning",
                            details={"CallStatus": call_status, "CallDuration": call_duration},
                            call_started_at=call_log.started_at,
                        )
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling call status callback: {e}")
        return {"status": "error", "message": str(e)}


def _maybe_enqueue_acw(call_sid: str, db: Session, background_tasks: BackgroundTasks):
    call_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
    if not call_log or not call_log.assistant_id:
        return
    from ..models import Assistant
    assistant = db.query(Assistant).filter(Assistant.id == call_log.assistant_id).first()
    if not assistant:
        return
    acw_config = assistant.acw_config or {}
    if acw_config.get("auto_run"):
        logger.info(f"Enqueueing ACW background task for call {call_sid}")
        background_tasks.add_task(run_acw_background, call_log.id)


@router.post("/connect-complete")
@router.get("/connect-complete")
async def connect_complete(request: Request, db: Session = Depends(get_db), background_tasks: BackgroundTasks = BackgroundTasks()):
    """
    Called when <Connect> completes (Stream ends).
    
    This is the action URL for <Connect>, called when the media stream ends.
    We can return TwiML here to continue the call (e.g., for transfers).
    
    Uses CallLogger service for status updates and saves conversation transcript.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        
        logger.info(f"Connect complete - SID: {call_sid}")
        
        call_handler = _get_call_handler()
        await call_handler.save_transcript_for_call(call_sid)
        
        call_logger = CallLogger(db)
        
        if call_logger.has_transfer(call_sid):
            call_log = call_logger.get_call_log(call_sid)
            transfer_mode = call_log.transfer_mode if call_log else None
            
            if transfer_mode == "cold":
                # Cold (SIP REFER) transfer: Twilio already exited the bridge.
                # No /transfer-status callbacks will arrive — finalize the record now.
                call_logger.complete_cold_transfer(call_sid)
                logger.info(f"Cold transfer call {call_sid} finalized at connect-complete")
                _maybe_enqueue_acw(call_sid, db, background_tasks)
            else:
                # Warm transfer: Twilio is still bridging. Keep call alive and wait
                # for /transfer-status callbacks to arrive with the final duration.
                logger.info(f"Warm transfer call {call_sid} — keeping alive for status callbacks")
            
            return Response(content="", media_type="application/xml")
        
        call_logger.complete_call(call_sid)
        logger.info(f"Marked call {call_sid} as completed via connect-complete")

        # Log call_ended here for calls where Twilio's terminal status callback
        # is not reliably delivered (common in dev; also a safety net for prod).
        # Deduped so we never write a second event if Twilio's webhook arrived first.
        call_log = call_logger.get_call_log(call_sid)
        if call_log and not _event_exists(db, call_log.id, "call_ended"):
            _write_event(
                db,
                call_log_id=call_log.id,
                event_type="call_ended",
                event_source="pipecat",
                severity="info",
                details={"source": "connect_complete"},
                call_started_at=call_log.started_at,
            )

        _maybe_enqueue_acw(call_sid, db, background_tasks)
        
        hangup_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""
        
        return Response(content=hangup_twiml, media_type="application/xml")
        
    except Exception as e:
        logger.exception(f"Error in connect-complete: {e}")
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")


@router.post("/transfer-status")
async def transfer_status_callback(request: Request, db: Session = Depends(get_db), background_tasks: BackgroundTasks = BackgroundTasks()):
    """
    Callback specifically for tracking transfer call status.
    
    When a call is transferred using Twilio's update call API,
    this endpoint receives status updates for the transferred leg.
    
    Twilio sends these events: initiated, ringing, answered, completed
    This lets us track:
    - When the transfer started ringing
    - When it was answered (transfer leg duration starts)
    - When it ended (transfer leg duration ends)
    
    Uses CallLogger service to update leg status.
    """
    try:
        form_data = await request.form()
        call_sid = str(form_data.get("CallSid", ""))
        call_status = str(form_data.get("CallStatus", "")) if form_data.get("CallStatus") else None
        call_duration = form_data.get("CallDuration")
        parent_call_sid = str(form_data.get("ParentCallSid", "")) if form_data.get("ParentCallSid") else None
        to_number = str(form_data.get("To", "")) if form_data.get("To") else None
        
        logger.info(f"Transfer status update - SID: {call_sid}, Parent: {parent_call_sid}, To: {to_number}, Status: {call_status}")
        
        if call_status:
            call_logger = CallLogger(db)
            duration_seconds = int(call_duration) if call_duration else None
            call_logger.update_leg_status(
                leg_call_sid=call_sid,
                status=call_status,
                duration_seconds=duration_seconds,
                parent_call_sid=parent_call_sid,
                to_number=to_number,
            )
            
            # Log transfer_connected / transfer_ended on parent call
            if parent_call_sid:
                parent_log = call_logger.get_call_log(parent_call_sid)
                if parent_log:
                    _TERMINAL = {"completed", "no-answer", "busy", "failed", "canceled"}
                    if call_status == "in-progress":
                        _write_event(
                            db,
                            call_log_id=parent_log.id,
                            event_type="transfer_connected",
                            event_source="twilio",
                            severity="info",
                            details={"ChildCallSid": call_sid, "To": to_number},
                            call_started_at=parent_log.started_at,
                        )
                    elif call_status in _TERMINAL:
                        _write_event(
                            db,
                            call_log_id=parent_log.id,
                            event_type="transfer_ended",
                            event_source="twilio",
                            severity="info",
                            details={"ChildCallSid": call_sid, "To": to_number, "CallStatus": call_status, "CallDuration": call_duration},
                            call_started_at=parent_log.started_at,
                        )

            _TERMINAL_TRANSFER_STATUSES = {"completed", "no-answer", "busy", "failed", "canceled"}
            if call_status in _TERMINAL_TRANSFER_STATUSES and parent_call_sid:
                logger.info(f"Transfer leg {call_sid} ended ({call_status}) — enqueueing ACW for parent call {parent_call_sid}")
                _maybe_enqueue_acw(parent_call_sid, db, background_tasks)
        
        return {"status": "received"}
        
    except Exception as e:
        logger.exception(f"Error handling transfer status callback: {e}")
        return {"status": "error", "message": str(e)}


def _validate_recording_webhook_signature(
    request: Request, form_data: dict, auth_token: str
) -> tuple[bool, str]:
    """
    Validate the X-Twilio-Signature on the recording-status callback.

    Skips validation (returns True) when no auth_token is available,
    matching the pattern used in the SMS webhook.
    """
    from ..config.domain import get_public_base_url

    fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    base = get_public_base_url(fallback_host=fallback_host)
    url = f"{base}/api/calls/recording-status"

    if not auth_token:
        logger.debug("Twilio signature validation skipped for recording-status — no auth token")
        return True, url

    try:
        from twilio.request_validator import RequestValidator

        signature = request.headers.get("X-Twilio-Signature", "")
        is_valid = RequestValidator(auth_token).validate(url, form_data, signature)
        return is_valid, url
    except Exception as exc:
        logger.warning(f"Twilio signature validation error on recording-status: {exc}")
        return False, url


@router.post("/recording-status")
async def recording_status_callback(request: Request, db: Session = Depends(get_db)):
    """
    Twilio recording status callback.

    Twilio POSTs here when a call recording's status changes.
    Validates the X-Twilio-Signature before processing to prevent replay attacks.
    When status is 'completed', saves the recording URL and SID to the call log.

    Twilio sends these fields (as form data):
        CallSid, RecordingSid, RecordingUrl, RecordingStatus, RecordingDuration
    """
    try:
        form_data = dict(await request.form())
        call_sid = str(form_data.get("CallSid", ""))
        recording_sid = str(form_data.get("RecordingSid", ""))
        recording_url = str(form_data.get("RecordingUrl", ""))
        recording_status = str(form_data.get("RecordingStatus", ""))

        # Validate Twilio signature using the hotel's sub-account auth token when
        # available, falling back to the platform-level token.
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if call_sid:
            call_log_for_auth = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            if call_log_for_auth:
                from ..models.hotel import Hotel as _Hotel
                _hotel = db.query(_Hotel).filter(_Hotel.id == call_log_for_auth.hotel_id).first()
                if _hotel and _hotel.twilio_sub_auth_token:
                    auth_token = _hotel.twilio_sub_auth_token

        is_valid, validated_url = _validate_recording_webhook_signature(request, form_data, auth_token)
        if not is_valid:
            logger.warning(
                f"Invalid Twilio signature on recording-status for CallSid={call_sid} "
                f"(validated against: {validated_url})"
            )
            from fastapi.responses import Response as _Response
            return _Response(status_code=403, content="Forbidden")

        logger.info(
            f"Recording status — CallSid: {call_sid}, RecordingSid: {recording_sid}, "
            f"Status: {recording_status}"
        )

        if recording_status == "completed" and call_sid and recording_url:
            media_url = recording_url.rstrip("/") + ".mp3"
            call_log = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
            if call_log:
                call_log.recording_url = media_url
                call_log.recording_sid = recording_sid
                db.commit()
                logger.info(f"Saved recording URL for call {call_sid}: {media_url}")
            else:
                logger.warning(f"No call log found for {call_sid} when saving recording")

        return {"status": "received"}

    except Exception as e:
        logger.exception(f"Error handling recording status callback: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Proxy endpoint to stream a Twilio call recording to authenticated clients.

    Requires a valid JWT (Bearer token in Authorization header).
    Verifies the authenticated user has call_logs.play_recordings permission
    for the account that owns the call. Platform admins bypass the check.

    The frontend fetches this via authFetch and creates a blob URL so the
    <audio> element can play it without needing to send auth headers.

    Twilio recordings require HTTP Basic auth — credentials stay server-side.
    """
    import httpx
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    call_log = db.query(CallLog).filter(CallLog.id == call_id).first()
    if not call_log:
        raise HTTPException(status_code=404, detail="Call log not found")

    check_account_permission(user, str(call_log.hotel_id), "call_logs.play_recordings", db)

    if not call_log.recording_url:
        raise HTTPException(status_code=404, detail="No recording available for this call")

    from ..models.hotel import Hotel
    hotel = db.query(Hotel).filter(Hotel.id == call_log.hotel_id).first()
    if hotel and hotel.twilio_sub_account_sid and hotel.twilio_sub_auth_token:
        twilio_account_sid = hotel.twilio_sub_account_sid
        twilio_auth_token = hotel.twilio_sub_auth_token
    else:
        twilio_account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        twilio_auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")

    if not twilio_account_sid or not twilio_auth_token:
        raise HTTPException(status_code=503, detail="Twilio credentials not configured")

    recording_url = call_log.recording_url

    try:
        async with httpx.AsyncClient() as client:
            twilio_response = await client.get(
                recording_url,
                auth=(twilio_account_sid, twilio_auth_token),
                follow_redirects=True,
                timeout=30.0,
            )

        if twilio_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Recording not found on Twilio")
        if twilio_response.status_code == 401 or twilio_response.status_code == 403:
            logger.error(
                f"Twilio auth error ({twilio_response.status_code}) fetching recording for call {call_id}"
            )
            raise HTTPException(status_code=502, detail="Could not authenticate with Twilio")
        if twilio_response.status_code != 200:
            logger.error(
                f"Twilio returned HTTP {twilio_response.status_code} for recording {call_id}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Twilio returned unexpected status {twilio_response.status_code}",
            )

        content_type = twilio_response.headers.get("content-type", "audio/mpeg")
        if "audio" not in content_type and "octet-stream" not in content_type:
            logger.warning(
                f"Unexpected content-type '{content_type}' from Twilio for call {call_id}"
            )
            raise HTTPException(status_code=502, detail="Twilio returned non-audio content")

        from fastapi.responses import Response as _BytesResponse
        return _BytesResponse(
            content=twilio_response.content,
            media_type="audio/mpeg",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error proxying recording for call {call_id}: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch recording from Twilio")


@router.get("/{call_id}/events")
async def get_call_events(call_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Return the event timeline for a specific call.

    Events are ordered chronologically by occurred_at.

    Response items include:
        event_type, event_source, severity, offset_ms, occurred_at, details
    """
    from ..models.call_event import CallEvent as CallEventModel

    try:
        call_log = db.query(CallLog).filter(CallLog.id == call_id).first()
        if not call_log:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Call not found")

        events = (
            db.query(CallEventModel)
            .filter(CallEventModel.call_log_id == call_log.id)
            .order_by(CallEventModel.occurred_at)
            .all()
        )

        return [e.to_dict() for e in events]

    except Exception as e:
        logger.exception(f"Error fetching events for call {call_id}: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Internal server error")

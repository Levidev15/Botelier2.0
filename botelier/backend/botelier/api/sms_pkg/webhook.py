"""
SMS Webhook endpoints.

  POST /api/sms/webhook  — Twilio inbound SMS (with signature validation)
  POST /api/sms/status   — Twilio delivery status callback
  GET  /api/sms/stream   — Server-Sent Events stream for real-time updates
"""

import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from sse_starlette.sse import EventSourceResponse

from botelier.database import get_db
from botelier.models.sms_conversation import SMSConversation, SMSMessage, MessageStatus
from botelier.services.sms_service import SMSService
from botelier.services.notification_broadcaster import broadcaster

router = APIRouter(prefix="/api/sms", tags=["SMS"])

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _build_webhook_url(request: Request) -> str:
    """
    Reconstruct the canonical public URL that Twilio signed against.

    Twilio signs the exact URL it called (e.g. https://my-app.replit.app/api/sms/webhook).
    We must reconstruct that same URL — NOT the internal server URL
    (http://0.0.0.0:3001/...) that FastAPI sees — or the signature check always fails.

    Priority:
      1. PUBLIC_BASE_URL env var (production custom domain or Replit dev URL)
      2. X-Forwarded-Host / Host headers as fallback
    """
    from botelier.config.domain import get_public_base_url
    fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    base = get_public_base_url(fallback_host=fallback_host)
    return f"{base}/api/sms/webhook"


def _validate_twilio_signature(request: Request, form_data: dict, auth_token: str) -> tuple[bool, str]:
    """
    Validate Twilio's X-Twilio-Signature header.

    Returns (is_valid, url_used) — the URL is included so callers can log it on failure.
    Skips validation (returns True) when no auth_token is available.
    """
    url = _build_webhook_url(request)

    if not auth_token:
        logger.debug(f"Twilio signature validation skipped — no auth token configured")
        return True, url

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)

        signature = request.headers.get("X-Twilio-Signature", "")
        logger.debug(f"Validating Twilio signature against: {url}")
        is_valid = validator.validate(url, dict(form_data), signature)
        return is_valid, url
    except Exception as e:
        logger.warning(f"Twilio signature validation error: {e}")
        return False, url


async def _get_auth_token_for_number(to_number: str, db: Session) -> str:
    """Return the auth token to use for signature validation.

    Prefers the hotel's Twilio sub-account token, falls back to the
    platform-level env var.
    """
    try:
        from botelier.models.phone_number import PhoneNumber
        from botelier.models.account import Account
        phone = db.query(PhoneNumber).filter(
            PhoneNumber.phone_number == to_number
        ).first()
        if phone:
            account = db.query(Account).filter(Account.id == phone.account_id).first()
            if account and account.twilio_sub_auth_token:
                return account.twilio_sub_auth_token
    except Exception:
        pass
    return os.environ.get("TWILIO_AUTH_TOKEN", "")


@router.post("/webhook")
async def sms_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Twilio incoming SMS webhook.

    Validates the X-Twilio-Signature header before processing.
    Returns an empty TwiML response so Twilio considers the call handled.

    Twilio form fields:
      From, To, Body, MessageSid, NumMedia, MediaUrl0..N
    """
    try:
        form_data = await request.form()

        from_number = form_data.get("From", "")
        to_number   = form_data.get("To", "")
        body        = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")

        # --- Signature validation ---
        auth_token = await _get_auth_token_for_number(to_number, db)
        is_valid, validated_url = _validate_twilio_signature(request, dict(form_data), auth_token)
        if not is_valid:
            logger.warning(
                f"Invalid Twilio signature for webhook from {from_number} to {to_number} "
                f"(validated against: {validated_url})"
            )
            from fastapi.responses import Response
            return Response(status_code=403, content="Forbidden")

        num_media = int(form_data.get("NumMedia", "0") or 0)
        media_urls = [
            url for i in range(num_media)
            if (url := form_data.get(f"MediaUrl{i}"))
        ]

        logger.info(f"📩 Incoming SMS: {from_number} -> {to_number} | {body[:50]}...")

        sms_service = SMSService(db)
        ai_response, conv_id, handoff_triggered = sms_service.process_incoming_sms(
            from_number=from_number,
            to_number=to_number,
            body=body,
            twilio_sid=message_sid,
            media_urls=media_urls or None,
        )

        # --- SSE broadcasts ---
        try:
            from botelier.models.phone_number import PhoneNumber
            phone_number = db.query(PhoneNumber).filter(
                PhoneNumber.phone_number == to_number
            ).first()
            if phone_number:
                account_id_str = str(phone_number.account_id)

                if conv_id:
                    conversation = db.query(SMSConversation).filter(
                        SMSConversation.id == conv_id,
                    ).first()
                else:
                    conversation = db.query(SMSConversation).filter(
                        SMSConversation.customer_number == from_number,
                        SMSConversation.botelier_number == to_number,
                        SMSConversation.account_id == phone_number.account_id,
                    ).order_by(desc(SMSConversation.last_message_at)).first()

                if conversation:
                    conv_id_str = str(conversation.id)

                    await broadcaster.broadcast(
                        hotel_id=account_id_str,
                        event_type="new_message",
                        data={
                            "conversation_id": conv_id_str,
                            "customer_number": from_number,
                            "preview": (body or "")[:100],
                            "account_id": account_id_str,
                        },
                    )

                    if ai_response:
                        await broadcaster.broadcast(
                            hotel_id=account_id_str,
                            event_type="new_reply",
                            data={
                                "conversation_id": conv_id_str,
                                "customer_number": from_number,
                                "preview": ai_response[:100],
                                "account_id": account_id_str,
                            },
                        )

                    if handoff_triggered:
                        await broadcaster.broadcast(
                            hotel_id=account_id_str,
                            event_type="handoff_requested",
                            data={
                                "conversation_id": conv_id_str,
                                "customer_number": from_number,
                                "account_id": account_id_str,
                                "last_ai_message": (ai_response or "")[:100],
                            },
                        )

        except Exception as broadcast_err:
            logger.warning(f"SSE broadcast failed (non-fatal): {broadcast_err}")

        return PlainTextResponse(content=_EMPTY_TWIML, media_type="text/xml")

    except Exception as e:
        logger.exception(f"Error processing SMS webhook: {e}")
        return PlainTextResponse(content=_EMPTY_TWIML, media_type="text/xml")


@router.post("/status")
async def sms_status_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Twilio SMS delivery status callback.
    Updates message delivery status (sent, delivered, failed).
    """
    try:
        form_data = await request.form()
        message_sid    = form_data.get("MessageSid", "")
        message_status = form_data.get("MessageStatus", "")

        if message_sid and message_status:
            msg = db.query(SMSMessage).filter(
                SMSMessage.twilio_sid == message_sid
            ).first()

            if msg:
                status_map = {
                    "sent":        MessageStatus.SENT.value,
                    "delivered":   MessageStatus.DELIVERED.value,
                    "failed":      MessageStatus.FAILED.value,
                    "undelivered": MessageStatus.FAILED.value,
                }
                msg.status = status_map.get(message_status, msg.status)
                db.commit()

        return PlainTextResponse(content="OK")

    except Exception as e:
        logger.exception(f"Error processing SMS status callback: {e}")
        return PlainTextResponse(content="OK")


@router.get("/stream")
async def sms_event_stream(
    hotel_id: str,
):
    """
    Server-Sent Events stream for real-time SMS notifications.

    Each browser tab opens one persistent connection. The server pushes
    events when messages arrive — no polling needed.

    Event types:
        new_message       — inbound customer SMS
        new_reply         — outbound agent/AI reply
        handoff_requested — AI escalated to human
        handler_changed   — agent took over or returned to AI
        keepalive         — every 15s to keep proxies alive
    """
    return EventSourceResponse(
        broadcaster.event_generator(hotel_id=hotel_id),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

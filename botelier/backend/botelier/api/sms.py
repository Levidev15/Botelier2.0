"""
SMS API - Twilio webhook and conversation management endpoints.

SECURITY: All conversation endpoints enforce hotel_id filtering
to prevent cross-tenant data access.
"""

import csv
import io
import os
import uuid as uuid_mod
from datetime import datetime, date
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import asc, desc, func, case, text
from sqlalchemy.orm import Session
from loguru import logger

from sse_starlette.sse import EventSourceResponse

from botelier.database import get_db
from botelier.models.sms_conversation import (
    SMSConversation, SMSMessage,
    ConversationStatus, MessageDirection, MessageSender, MessageStatus
)
from botelier.models.sms_template import SMSTemplate, SMSNotificationSettings
from botelier.services.sms_service import SMSService
from botelier.services.notification_broadcaster import broadcaster


router = APIRouter(prefix="/api/sms", tags=["SMS"])


@router.post("/webhook")
async def sms_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Twilio incoming SMS webhook.

    Twilio sends form-encoded data with fields:
    - From: Sender phone number
    - To: Recipient phone number (our Botelier number)
    - Body: Message text
    - MessageSid: Twilio message SID
    - NumMedia: Number of media attachments
    - MediaUrl0, MediaUrl1, etc.: Media URLs
    """
    try:
        form_data = await request.form()

        from_number = form_data.get("From", "")
        to_number = form_data.get("To", "")
        body = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")

        num_media = int(form_data.get("NumMedia", "0"))
        media_urls = []
        for i in range(num_media):
            url = form_data.get(f"MediaUrl{i}")
            if url:
                media_urls.append(url)

        logger.info(f"📩 Incoming SMS: {from_number} -> {to_number} | Body: {body[:50]}...")

        sms_service = SMSService(db)
        response_text = sms_service.process_incoming_sms(
            from_number=from_number,
            to_number=to_number,
            body=body,
            twilio_sid=message_sid,
            media_urls=media_urls if media_urls else None,
        )

        # After processing, broadcast a real-time notification to all SSE
        # clients watching this hotel so their conversation lists update instantly.
        try:
            from botelier.models.phone_number import PhoneNumber
            phone_number = db.query(PhoneNumber).filter(
                PhoneNumber.phone_number == to_number
            ).first()
            if phone_number:
                conversation = db.query(SMSConversation).filter(
                    SMSConversation.customer_number == from_number,
                    SMSConversation.botelier_number == to_number,
                    SMSConversation.hotel_id == phone_number.hotel_id,
                ).order_by(desc(SMSConversation.last_message_at)).first()

                if conversation:
                    await broadcaster.broadcast(
                        hotel_id=str(phone_number.hotel_id),
                        event_type="new_message",
                        data={
                            "conversation_id": str(conversation.id),
                            "customer_number": from_number,
                            "preview": body[:100] if body else "",
                            "hotel_id": str(phone_number.hotel_id),
                        },
                    )
        except Exception as broadcast_err:
            logger.warning(f"SSE broadcast failed (non-fatal): {broadcast_err}")

        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response></Response>"
        )
        return PlainTextResponse(content=twiml, media_type="text/xml")

    except Exception as e:
        logger.exception(f"Error processing SMS webhook: {e}")
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response></Response>"
        )
        return PlainTextResponse(content=twiml, media_type="text/xml")


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
        message_sid = form_data.get("MessageSid", "")
        message_status = form_data.get("MessageStatus", "")

        if message_sid and message_status:
            msg = db.query(SMSMessage).filter(
                SMSMessage.twilio_sid == message_sid
            ).first()

            if msg:
                status_map = {
                    "sent": MessageStatus.SENT.value,
                    "delivered": MessageStatus.DELIVERED.value,
                    "failed": MessageStatus.FAILED.value,
                    "undelivered": MessageStatus.FAILED.value,
                }
                msg.status = status_map.get(message_status, msg.status)
                db.commit()

        return PlainTextResponse(content="OK")

    except Exception as e:
        logger.exception(f"Error processing SMS status callback: {e}")
        return PlainTextResponse(content="OK")


_SORT_COLUMNS = {
    "last_message_at": SMSConversation.last_message_at,
    "started_at": SMSConversation.started_at,
    "message_count": SMSConversation.message_count,
    "closed_at": SMSConversation.closed_at,
}


@router.get("/conversations")
async def list_conversations(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by customer phone number"),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    handler_mode: Optional[str] = Query(None, description="Filter by handler: 'ai' or 'human'"),
    botelier_number: Optional[str] = Query(None, description="Filter by hotel phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter conversations started on or after this datetime (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Filter conversations started on or before this datetime (ISO 8601)"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort field: last_message_at | started_at | message_count | closed_at"),
    sort_order: Optional[str] = Query("desc", description="Sort direction: asc | desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get paginated SMS conversations for a hotel."""
    try:
        query = db.query(SMSConversation).filter(
            SMSConversation.hotel_id == hotel_id
        )

        if status:
            query = query.filter(SMSConversation.status == status)

        if search:
            query = query.filter(
                SMSConversation.customer_number.ilike(f"%{search}%")
            )

        if assistant_id:
            query = query.filter(SMSConversation.assistant_id == assistant_id)

        if handler_mode and handler_mode in ("ai", "human"):
            query = query.filter(SMSConversation.handler_mode == handler_mode)

        if botelier_number:
            query = query.filter(SMSConversation.botelier_number == botelier_number)

        if date_from:
            query = query.filter(SMSConversation.started_at >= date_from)

        if date_to:
            query = query.filter(SMSConversation.started_at <= date_to)

        total = query.count()

        sort_col = _SORT_COLUMNS.get(sort_by or "last_message_at", SMSConversation.last_message_at)
        order_fn = asc if (sort_order or "desc").lower() == "asc" else desc

        conversations = query.order_by(
            order_fn(sort_col)
        ).offset((page - 1) * limit).limit(limit).all()

        last_messages = {}
        if conversations:
            conv_ids = [c.id for c in conversations]
            from sqlalchemy import func
            subq = db.query(
                SMSMessage.conversation_id,
                func.max(SMSMessage.created_at).label("max_created")
            ).filter(
                SMSMessage.conversation_id.in_(conv_ids)
            ).group_by(SMSMessage.conversation_id).subquery()

            latest_msgs = db.query(SMSMessage).join(
                subq,
                (SMSMessage.conversation_id == subq.c.conversation_id) &
                (SMSMessage.created_at == subq.c.max_created)
            ).all()

            for msg in latest_msgs:
                last_messages[str(msg.conversation_id)] = msg.content[:100]

        results = []
        for conv in conversations:
            d = conv.to_dict()
            d["last_message_preview"] = last_messages.get(str(conv.id), "")
            results.append(d)

        return {
            "conversations": results,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        }

    except Exception as e:
        logger.exception(f"Error listing SMS conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to load conversations")


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Get a single SMS conversation with all messages."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == hotel_id,
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = db.query(SMSMessage).filter(
            SMSMessage.conversation_id == conversation_id
        ).order_by(SMSMessage.created_at.asc()).all()

        result = conversation.to_dict()
        result["messages"] = [msg.to_dict() for msg in messages]

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting SMS conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to load conversation")


class CloseConversationRequest(BaseModel):
    hotel_id: str


@router.post("/conversations/{conversation_id}/close")
async def close_conversation(
    conversation_id: UUID,
    request: CloseConversationRequest,
    db: Session = Depends(get_db),
):
    """Close an SMS conversation."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.status = ConversationStatus.CLOSED.value
        conversation.closed_at = datetime.utcnow()
        db.commit()

        return {"success": True, "conversation": conversation.to_dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error closing SMS conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to close conversation")


class MarkReadRequest(BaseModel):
    hotel_id: str


@router.post("/conversations/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: UUID,
    request: MarkReadRequest,
    db: Session = Depends(get_db),
):
    """Mark a conversation as read (updates last_read_at timestamp)."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.last_read_at = datetime.utcnow()
        db.commit()

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error marking conversation as read: {e}")
        raise HTTPException(status_code=500, detail="Failed to mark as read")


class PresenceRequest(BaseModel):
    hotel_id: str
    agent_id: str
    agent_name: str


@router.post("/conversations/{conversation_id}/presence")
async def set_agent_presence(
    conversation_id: UUID,
    request: PresenceRequest,
    db: Session = Depends(get_db),
):
    """Set the active agent presence on a conversation (heartbeat every 15s)."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.active_agent_id = UUID(request.agent_id)
        conversation.active_agent_name = request.agent_name
        conversation.agent_active_at = datetime.utcnow()
        db.commit()

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error setting agent presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to set presence")


class ClearPresenceRequest(BaseModel):
    hotel_id: str
    agent_id: str


@router.delete("/conversations/{conversation_id}/presence")
async def clear_agent_presence(
    conversation_id: UUID,
    request: ClearPresenceRequest,
    db: Session = Depends(get_db),
):
    """Clear the active agent presence from a conversation."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.active_agent_id and str(conversation.active_agent_id) == request.agent_id:
            conversation.active_agent_id = None
            conversation.active_agent_name = None
            conversation.agent_active_at = None
            db.commit()

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error clearing agent presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear presence")


class AgentReplyRequest(BaseModel):
    hotel_id: str
    message: str
    media_urls: Optional[list] = None


@router.post("/conversations/{conversation_id}/reply")
async def agent_reply(
    conversation_id: UUID,
    request: AgentReplyRequest,
    db: Session = Depends(get_db),
):
    """Send a manual reply from a human agent in an SMS conversation."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.status != ConversationStatus.ACTIVE.value:
            raise HTTPException(status_code=400, detail="Cannot reply to a closed conversation")

        message_text = request.message.strip()
        if not message_text and not request.media_urls:
            raise HTTPException(status_code=400, detail="Message or attachment is required")

        sms_service = SMSService(db)
        twilio_sid = sms_service._send_twilio_sms(
            from_number=conversation.botelier_number,
            to_number=conversation.customer_number,
            body=message_text or "",
            hotel_id=conversation.hotel_id,
            media_urls=request.media_urls,
        )

        msg = SMSMessage(
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND.value,
            sender=MessageSender.AGENT.value,
            content=message_text or "",
            media_urls=request.media_urls,
            status=MessageStatus.SENT.value if twilio_sid else MessageStatus.FAILED.value,
            twilio_sid=twilio_sid,
        )
        db.add(msg)

        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        if conversation.first_response_at is None:
            conversation.first_response_at = datetime.utcnow()
        db.commit()

        # Notify other connected agents that a reply was sent
        try:
            await broadcaster.broadcast(
                hotel_id=str(conversation.hotel_id),
                event_type="new_reply",
                data={
                    "conversation_id": str(conversation.id),
                    "customer_number": conversation.customer_number,
                    "preview": (message_text or "")[:100],
                    "hotel_id": str(conversation.hotel_id),
                },
            )
        except Exception as broadcast_err:
            logger.warning(f"SSE broadcast failed (non-fatal): {broadcast_err}")

        return {
            "success": True,
            "message": msg.to_dict(),
            "twilio_sid": twilio_sid,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error sending agent reply: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reply")


class GenerateSMSSummaryRequest(BaseModel):
    hotel_id: str


@router.post("/conversations/{conversation_id}/generate-summary")
async def generate_sms_summary(
    conversation_id: UUID,
    request: GenerateSMSSummaryRequest,
    db: Session = Depends(get_db),
):
    """Generate an AI summary of an SMS conversation."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.hotel_id == UUID(request.hotel_id),
        ).first()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = db.query(SMSMessage).filter(
            SMSMessage.conversation_id == conversation_id
        ).order_by(SMSMessage.created_at.asc()).all()

        if not messages:
            raise HTTPException(status_code=400, detail="No messages in this conversation")

        transcript_text = ""
        for msg in messages:
            role = "Customer" if msg.sender == MessageSender.CUSTOMER.value else "AI"
            transcript_text += f"{role}: {msg.content}\n"

        import os
        from openai import OpenAI

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        prompt = f"""Analyze this SMS conversation and provide:
1. A concise 2-3 sentence summary of what happened
2. Key points: customer intent, actions taken, and outcome

SMS Conversation:
{transcript_text}

Respond in JSON format:
{{
    "summary": "...",
    "key_points": ["...", "..."]
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a customer service analyst. Provide clear, professional summaries of SMS conversations."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        import json
        result = json.loads(response.choices[0].message.content)

        summary = result.get("summary", "")
        key_points = result.get("key_points", [])

        full_summary = summary
        if key_points:
            full_summary += "\n\nKey Points:\n" + "\n".join([f"- {p}" for p in key_points])

        conversation.ai_summary = full_summary
        db.commit()

        return {
            "success": True,
            "summary": full_summary,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating SMS summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")


ALLOWED_UPLOAD_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
}
MAX_FILE_SIZE = 5 * 1024 * 1024
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    hotel_id: str = Form(...),
    request: Request = None,
):
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail=f"File type {file.content_type} not allowed")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5MB limit")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    unique_name = f"{uuid_mod.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if replit_domain:
        base_url = f"https://{replit_domain}"
    elif request:
        forwarded_host = request.headers.get("x-forwarded-host", "")
        if forwarded_host:
            base_url = f"https://{forwarded_host}"
        else:
            base_url = str(request.base_url).rstrip("/")
    else:
        base_url = "http://localhost:3001"
    public_url = f"{base_url}/uploads/{unique_name}"

    return {
        "success": True,
        "url": public_url,
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(contents),
    }


class TemplateRequest(BaseModel):
    hotel_id: str
    name: str
    content: str
    category: Optional[str] = None
    is_active: bool = True


@router.get("/templates")
async def list_templates(
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    templates = db.query(SMSTemplate).filter(
        SMSTemplate.hotel_id == UUID(hotel_id),
    ).order_by(SMSTemplate.category, SMSTemplate.name).all()
    return [t.to_dict() for t in templates]


@router.post("/templates")
async def create_template(
    request: TemplateRequest,
    db: Session = Depends(get_db),
):
    template = SMSTemplate(
        hotel_id=UUID(request.hotel_id),
        name=request.name,
        content=request.content,
        category=request.category,
        is_active=request.is_active,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template.to_dict()


@router.put("/templates/{template_id}")
async def update_template(
    template_id: UUID,
    request: TemplateRequest,
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.hotel_id == UUID(request.hotel_id),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.name = request.name
    template.content = request.content
    template.category = request.category
    template.is_active = request.is_active
    template.updated_at = datetime.utcnow()
    db.commit()
    return template.to_dict()


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    template = db.query(SMSTemplate).filter(
        SMSTemplate.id == template_id,
        SMSTemplate.hotel_id == UUID(hotel_id),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"success": True}


class NotificationSettingsRequest(BaseModel):
    hotel_id: str
    sound_enabled: bool = True
    visual_enabled: bool = True
    threshold: int = 1
    sound_type: str = "chime"


@router.get("/settings/notifications")
async def get_notification_settings(
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.hotel_id == UUID(hotel_id),
    ).first()
    if not settings:
        return {
            "sound_enabled": True,
            "visual_enabled": True,
            "threshold": 1,
            "sound_type": "chime",
        }
    return settings.to_dict()


@router.put("/settings/notifications")
async def update_notification_settings(
    request: NotificationSettingsRequest,
    db: Session = Depends(get_db),
):
    settings = db.query(SMSNotificationSettings).filter(
        SMSNotificationSettings.hotel_id == UUID(request.hotel_id),
    ).first()

    if not settings:
        settings = SMSNotificationSettings(
            hotel_id=UUID(request.hotel_id),
            sound_enabled=request.sound_enabled,
            visual_enabled=request.visual_enabled,
            threshold=str(request.threshold),
            sound_type=request.sound_type,
        )
        db.add(settings)
    else:
        settings.sound_enabled = request.sound_enabled
        settings.visual_enabled = request.visual_enabled
        settings.threshold = str(request.threshold)
        settings.sound_type = request.sound_type
        settings.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(settings)
    return settings.to_dict()


@router.get("/unread-count")
async def get_unread_count(
    hotel_id: str = Query(...),
    db: Session = Depends(get_db),
):
    count = db.query(func.count(SMSConversation.id)).filter(
        SMSConversation.hotel_id == UUID(hotel_id),
        SMSConversation.status == ConversationStatus.ACTIVE.value,
        SMSConversation.last_message_at > func.coalesce(
            SMSConversation.last_read_at,
            datetime(2000, 1, 1),
        ),
    ).scalar() or 0

    return {"unread_count": count}


@router.get("/stats")
async def get_sms_stats(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    date_from: Optional[datetime] = Query(None, description="Start of reporting window (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End of reporting window (ISO 8601)"),
    assistant_id: Optional[UUID] = Query(None, description="Limit stats to one assistant"),
    botelier_number: Optional[str] = Query(None, description="Limit stats to one hotel phone number"),
    db: Session = Depends(get_db),
):
    """
    Aggregated analytics for SMS conversations.

    All figures are scoped to hotel_id. Optional filters narrow the window
    by date range, assistant, or hotel phone number.
    """
    try:
        from botelier.models.assistant import Assistant
        from botelier.models.disposition import AssistantDisposition

        def _base_conv_q():
            q = db.query(SMSConversation).filter(SMSConversation.hotel_id == hotel_id)
            if date_from:
                q = q.filter(SMSConversation.started_at >= date_from)
            if date_to:
                q = q.filter(SMSConversation.started_at <= date_to)
            if assistant_id:
                q = q.filter(SMSConversation.assistant_id == assistant_id)
            if botelier_number:
                q = q.filter(SMSConversation.botelier_number == botelier_number)
            return q

        # --- Overview: conversation-level counts ---
        status_counts = (
            db.query(SMSConversation.status, func.count(SMSConversation.id))
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by(SMSConversation.status)
            .all()
        )
        status_map = {s: c for s, c in status_counts}

        handler_counts = (
            db.query(SMSConversation.handler_mode, func.count(SMSConversation.id))
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by(SMSConversation.handler_mode)
            .all()
        )
        handler_map = {h: c for h, c in handler_counts}

        total_conversations = sum(status_map.values())

        conv_agg = (
            db.query(
                func.sum(SMSConversation.message_count).label("total_msg"),
                func.avg(SMSConversation.message_count).label("avg_msg"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .one()
        )

        # --- Message-level stats (direction/sender breakdown) ---
        conv_ids_subq = _base_conv_q().with_entities(SMSConversation.id).subquery()

        msg_agg = (
            db.query(
                SMSMessage.direction,
                SMSMessage.sender,
                func.count(SMSMessage.id).label("cnt"),
                func.sum(SMSMessage.tokens_used).label("tokens"),
            )
            .filter(SMSMessage.conversation_id.in_(conv_ids_subq))
            .group_by(SMSMessage.direction, SMSMessage.sender)
            .all()
        )

        inbound_total = sum(r.cnt for r in msg_agg if r.direction == "inbound")
        outbound_total = sum(r.cnt for r in msg_agg if r.direction == "outbound")
        ai_responses = sum(r.cnt for r in msg_agg if r.sender == "ai")
        agent_responses = sum(r.cnt for r in msg_agg if r.sender == "agent")
        total_tokens = sum((r.tokens or 0) for r in msg_agg)

        # --- Response time ---
        rt_row = (
            db.query(
                func.avg(
                    func.extract("epoch", SMSConversation.first_response_at - SMSConversation.started_at)
                ).label("avg_rt"),
                func.count(SMSConversation.id).label("cnt"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(SMSConversation.first_response_at.isnot(None))
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .one()
        )

        # --- Volume by day ---
        day_label = func.date_trunc("day", SMSConversation.started_at).label("day")
        volume_rows = (
            db.query(day_label, func.count(SMSConversation.id).label("conv_count"))
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by("day")
            .order_by("day")
            .all()
        )

        # Message volume by day requires a join
        msg_day_label = func.date_trunc("day", SMSMessage.created_at).label("day")
        msg_volume_rows = (
            db.query(msg_day_label, func.count(SMSMessage.id).label("msg_count"))
            .filter(SMSMessage.conversation_id.in_(conv_ids_subq))
            .group_by("day")
            .order_by("day")
            .all()
        )
        msg_volume_map = {
            r.day.date().isoformat() if r.day else None: r.msg_count
            for r in msg_volume_rows
        }

        volume_by_day = [
            {
                "date": r.day.date().isoformat() if r.day else None,
                "conversations_started": r.conv_count,
                "messages": msg_volume_map.get(r.day.date().isoformat() if r.day else None, 0),
            }
            for r in volume_rows
        ]

        # --- By phone number ---
        by_number_rows = (
            db.query(
                SMSConversation.botelier_number,
                func.count(SMSConversation.id).label("conv_count"),
                func.sum(SMSConversation.message_count).label("msg_count"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .group_by(SMSConversation.botelier_number)
            .order_by(desc("conv_count"))
            .all()
        )

        # --- By assistant ---
        by_asst_rows = (
            db.query(
                SMSConversation.assistant_id,
                func.count(SMSConversation.id).label("conv_count"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(SMSConversation.assistant_id.isnot(None))
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by(SMSConversation.assistant_id)
            .order_by(desc("conv_count"))
            .all()
        )

        asst_ids = [r.assistant_id for r in by_asst_rows]
        asst_names = {}
        if asst_ids:
            assistants = db.query(Assistant.id, Assistant.name).filter(
                Assistant.id.in_(asst_ids)
            ).all()
            asst_names = {str(a.id): a.name for a in assistants}

        # --- Dispositions ---
        disp_rows = (
            db.query(
                SMSConversation.disposition_id,
                func.count(SMSConversation.id).label("cnt"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(SMSConversation.disposition_id.isnot(None))
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by(SMSConversation.disposition_id)
            .order_by(desc("cnt"))
            .all()
        )

        disp_ids = [r.disposition_id for r in disp_rows]
        disp_info = {}
        if disp_ids:
            disps = db.query(AssistantDisposition).filter(
                AssistantDisposition.id.in_(disp_ids)
            ).all()
            disp_info = {str(d.id): {"name": d.name, "color": d.color} for d in disps}

        # --- Top customers ---
        top_customers = (
            db.query(
                SMSConversation.customer_number,
                func.count(SMSConversation.id).label("conversation_count"),
                func.sum(SMSConversation.message_count).label("message_count"),
            )
            .filter(SMSConversation.hotel_id == hotel_id)
            .filter(*(
                [SMSConversation.started_at >= date_from] if date_from else []
            ))
            .filter(*(
                [SMSConversation.started_at <= date_to] if date_to else []
            ))
            .filter(*(
                [SMSConversation.assistant_id == assistant_id] if assistant_id else []
            ))
            .filter(*(
                [SMSConversation.botelier_number == botelier_number] if botelier_number else []
            ))
            .group_by(SMSConversation.customer_number)
            .order_by(desc("conversation_count"))
            .limit(20)
            .all()
        )

        avg_rt = float(rt_row.avg_rt) if rt_row.avg_rt else None

        return {
            "period": {
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None,
            },
            "overview": {
                "total_conversations": total_conversations,
                "active": status_map.get("active", 0),
                "closed": status_map.get("closed", 0),
                "opted_out": status_map.get("opted_out", 0),
                "ai_handled": handler_map.get("ai", 0),
                "human_handled": handler_map.get("human", 0),
                "total_messages": int(conv_agg.total_msg or 0),
                "inbound_messages": inbound_total,
                "outbound_messages": outbound_total,
                "ai_responses": ai_responses,
                "agent_responses": agent_responses,
                "avg_messages_per_conversation": round(float(conv_agg.avg_msg or 0), 2),
                "total_tokens_used": int(total_tokens),
            },
            "volume_by_day": volume_by_day,
            "response_time": {
                "avg_first_response_seconds": round(avg_rt, 1) if avg_rt is not None else None,
                "conversations_with_response": rt_row.cnt,
            },
            "by_phone_number": [
                {
                    "botelier_number": r.botelier_number,
                    "conversations": r.conv_count,
                    "messages": int(r.msg_count or 0),
                }
                for r in by_number_rows
            ],
            "by_assistant": [
                {
                    "assistant_id": str(r.assistant_id),
                    "assistant_name": asst_names.get(str(r.assistant_id), "Unknown"),
                    "conversations": r.conv_count,
                }
                for r in by_asst_rows
            ],
            "dispositions": [
                {
                    "disposition_id": str(r.disposition_id),
                    "name": disp_info.get(str(r.disposition_id), {}).get("name", "Unknown"),
                    "color": disp_info.get(str(r.disposition_id), {}).get("color"),
                    "count": r.cnt,
                }
                for r in disp_rows
            ],
            "top_customers": [
                {
                    "customer_number": r.customer_number,
                    "conversation_count": r.conversation_count,
                    "message_count": int(r.message_count or 0),
                }
                for r in top_customers
            ],
        }

    except Exception as e:
        logger.exception(f"Error generating SMS stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate SMS stats")


@router.get("/export")
async def export_sms_conversations(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by status"),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    handler_mode: Optional[str] = Query(None, description="Filter by handler: 'ai' or 'human'"),
    botelier_number: Optional[str] = Query(None, description="Filter by hotel phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter started_at >= date_from"),
    date_to: Optional[datetime] = Query(None, description="Filter started_at <= date_to"),
    db: Session = Depends(get_db),
):
    """
    Export SMS conversations as a CSV file (max 10,000 rows).

    CSV columns:
      id, started_at, closed_at, status, handler_mode, customer_number,
      botelier_number, message_count, first_response_at, response_time_seconds,
      ai_responses, agent_responses, tools_used, disposition, ai_summary, assistant_id
    """
    try:
        query = (
            db.query(SMSConversation)
            .filter(SMSConversation.hotel_id == hotel_id)
        )

        if status:
            query = query.filter(SMSConversation.status == status)
        if assistant_id:
            query = query.filter(SMSConversation.assistant_id == assistant_id)
        if handler_mode and handler_mode in ("ai", "human"):
            query = query.filter(SMSConversation.handler_mode == handler_mode)
        if botelier_number:
            query = query.filter(SMSConversation.botelier_number == botelier_number)
        if date_from:
            query = query.filter(SMSConversation.started_at >= date_from)
        if date_to:
            query = query.filter(SMSConversation.started_at <= date_to)

        conversations = (
            query.order_by(desc(SMSConversation.started_at)).limit(10_000).all()
        )

        # Preload message sender counts for all conversations in one query
        conv_ids = [c.id for c in conversations]
        sender_counts: dict[str, dict[str, int]] = {}
        if conv_ids:
            rows = (
                db.query(
                    SMSMessage.conversation_id,
                    SMSMessage.sender,
                    func.count(SMSMessage.id).label("cnt"),
                )
                .filter(SMSMessage.conversation_id.in_(conv_ids))
                .group_by(SMSMessage.conversation_id, SMSMessage.sender)
                .all()
            )
            for r in rows:
                cid = str(r.conversation_id)
                if cid not in sender_counts:
                    sender_counts[cid] = {}
                sender_counts[cid][r.sender] = r.cnt

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "id", "started_at", "closed_at", "status", "handler_mode",
            "customer_number", "botelier_number", "message_count",
            "first_response_at", "response_time_seconds",
            "ai_responses", "agent_responses", "tools_used",
            "disposition", "ai_summary", "assistant_id",
        ])

        for conv in conversations:
            cid = str(conv.id)
            counts = sender_counts.get(cid, {})

            response_time = None
            if conv.first_response_at and conv.started_at:
                response_time = round(
                    (conv.first_response_at - conv.started_at).total_seconds(), 1
                )

            writer.writerow([
                cid,
                conv.started_at.isoformat() + "Z" if conv.started_at else "",
                conv.closed_at.isoformat() + "Z" if conv.closed_at else "",
                conv.status or "",
                conv.handler_mode or "ai",
                conv.customer_number or "",
                conv.botelier_number or "",
                conv.message_count or 0,
                conv.first_response_at.isoformat() + "Z" if conv.first_response_at else "",
                response_time if response_time is not None else "",
                counts.get("ai", 0),
                counts.get("agent", 0),
                conv.tools_used or "",
                conv.disposition.name if conv.disposition else "",
                (conv.ai_summary or "").replace("\n", " "),
                str(conv.assistant_id) if conv.assistant_id else "",
            ])

        filename = f"sms-conversations-{datetime.utcnow().date().isoformat()}.csv"
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.exception(f"Error exporting SMS conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to export conversations")


@router.get("/stream")
async def sms_event_stream(
    hotel_id: str = Query(..., description="Hotel ID to subscribe for real-time events"),
):
    """
    Server-Sent Events stream for real-time SMS notifications.

    Each browser tab opens one persistent connection here. The server pushes
    events when messages arrive — no polling needed.

    Event types:
        new_message  — a customer SMS arrived (updates conversation list)
        new_reply    — an agent sent a reply (syncs other agents' views)
        keepalive    — sent every 15 s to keep proxies from closing the connection

    Event data shape (JSON):
        { "conversation_id": "...", "customer_number": "...", "preview": "...", "hotel_id": "..." }
    """
    return EventSourceResponse(
        broadcaster.event_generator(hotel_id=hotel_id),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""
SMS API - Twilio webhook and conversation management endpoints.

SECURITY: All conversation endpoints enforce hotel_id filtering
to prevent cross-tenant data access.
"""

import os
import uuid as uuid_mod
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.sms_conversation import (
    SMSConversation, SMSMessage,
    ConversationStatus, MessageDirection, MessageSender, MessageStatus
)
from botelier.models.sms_template import SMSTemplate, SMSNotificationSettings
from botelier.services.sms_service import SMSService


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


@router.get("/conversations")
async def list_conversations(
    hotel_id: UUID = Query(..., description="Hotel ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by phone number"),
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

        total = query.count()

        conversations = query.order_by(
            desc(SMSConversation.last_message_at)
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
        db.commit()

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

    base_url = str(request.base_url).rstrip("/") if request else "http://localhost:3001"
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

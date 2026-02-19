"""
SMS API - Twilio webhook and conversation management endpoints.

SECURITY: All conversation endpoints enforce hotel_id filtering
to prevent cross-tenant data access.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.sms_conversation import (
    SMSConversation, SMSMessage,
    ConversationStatus, MessageDirection, MessageSender, MessageStatus
)
from botelier.models.assistant import Assistant
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

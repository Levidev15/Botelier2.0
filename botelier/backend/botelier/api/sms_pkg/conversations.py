"""
SMS Conversation management endpoints.

  GET    /api/sms/conversations
  GET    /api/sms/conversations/{id}
  POST   /api/sms/conversations/{id}/take-over
  POST   /api/sms/conversations/{id}/return-to-ai
  POST   /api/sms/conversations/{id}/close
  POST   /api/sms/conversations/{id}/read
  POST   /api/sms/conversations/{id}/presence
  DELETE /api/sms/conversations/{id}/presence
  POST   /api/sms/conversations/{id}/reply
  POST   /api/sms/conversations/{id}/generate-summary
"""

import json
import os
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.sms_conversation import (
    SMSConversation, SMSMessage,
    ConversationStatus, MessageDirection, MessageSender, MessageStatus,
)
from botelier.services.sms_service import SMSService
from botelier.services.notification_broadcaster import broadcaster

router = APIRouter(prefix="/api/sms", tags=["SMS"])

_SORT_COLUMNS = {
    "last_message_at": SMSConversation.last_message_at,
    "started_at":      SMSConversation.started_at,
    "message_count":   SMSConversation.message_count,
    "closed_at":       SMSConversation.closed_at,
}

_SUMMARY_SENDER_LABEL = {
    MessageSender.CUSTOMER.value: "Customer",
    MessageSender.AI.value:       "AI",
    MessageSender.AGENT.value:    "Agent",
}

_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


@router.get("/conversations")
async def list_conversations(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by customer phone number"),
    assistant_id: Optional[UUID] = Query(None, description="Filter by assistant"),
    handler_mode: Optional[str] = Query(None, description="Filter by handler: 'ai' or 'human'"),
    needs_attention: Optional[bool] = Query(None, description="Filter by needs_attention flag"),
    botelier_number: Optional[str] = Query(None, description="Filter by hotel phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter conversations started on or after (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Filter conversations started on or before (ISO 8601)"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort field"),
    sort_order: Optional[str] = Query("desc", description="Sort direction: asc | desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get paginated SMS conversations for an account."""
    try:
        query = db.query(SMSConversation).filter(SMSConversation.account_id == account_id)

        if status:
            query = query.filter(SMSConversation.status == status)
        if search:
            query = query.filter(
                or_(
                    SMSConversation.customer_number.ilike(f"%{search}%"),
                    SMSConversation.reference_id.ilike(f"%{search}%"),
                )
            )
        if assistant_id:
            query = query.filter(SMSConversation.assistant_id == assistant_id)
        if handler_mode and handler_mode in ("ai", "human"):
            query = query.filter(SMSConversation.handler_mode == handler_mode)
        if needs_attention is not None:
            query = query.filter(SMSConversation.needs_attention == needs_attention)
        if botelier_number:
            query = query.filter(SMSConversation.botelier_number == botelier_number)
        if date_from:
            query = query.filter(SMSConversation.started_at >= date_from)
        if date_to:
            query = query.filter(SMSConversation.started_at <= date_to)

        total = query.count()

        sort_col = _SORT_COLUMNS.get(sort_by or "last_message_at", SMSConversation.last_message_at)
        order_fn = asc if (sort_order or "desc").lower() == "asc" else desc
        conversations = query.order_by(order_fn(sort_col)).offset((page - 1) * limit).limit(limit).all()

        last_messages: dict = {}
        if conversations:
            conv_ids = [c.id for c in conversations]
            subq = db.query(
                SMSMessage.conversation_id,
                func.max(SMSMessage.created_at).label("max_created"),
            ).filter(SMSMessage.conversation_id.in_(conv_ids)).group_by(SMSMessage.conversation_id).subquery()

            latest = db.query(SMSMessage).join(
                subq,
                (SMSMessage.conversation_id == subq.c.conversation_id) &
                (SMSMessage.created_at == subq.c.max_created),
            ).all()
            for msg in latest:
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
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    db: Session = Depends(get_db),
):
    """Get a single SMS conversation with all messages."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.account_id == account_id,
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


class HandlerModeRequest(BaseModel):
    account_id: str


@router.post("/conversations/{conversation_id}/take-over")
async def take_over_conversation(
    conversation_id: UUID,
    request: HandlerModeRequest,
    db: Session = Depends(get_db),
):
    """Agent manually takes over a conversation — AI goes silent."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.account_id == UUID(request.account_id),
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.handler_mode = "human"
        conversation.needs_attention = True
        db.commit()

        try:
            await broadcaster.broadcast(
                hotel_id=request.account_id,
                event_type="handler_changed",
                data={
                    "conversation_id": str(conversation_id),
                    "handler_mode": "human",
                    "needs_attention": True,
                },
            )
        except Exception as e:
            logger.warning(f"SSE broadcast failed (non-fatal): {e}")

        return {"success": True, "handler_mode": "human", "needs_attention": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error taking over conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to take over conversation")


@router.post("/conversations/{conversation_id}/return-to-ai")
async def return_to_ai(
    conversation_id: UUID,
    request: HandlerModeRequest,
    db: Session = Depends(get_db),
):
    """Return a conversation to AI handling."""
    try:
        conversation = db.query(SMSConversation).filter(
            SMSConversation.id == conversation_id,
            SMSConversation.account_id == UUID(request.account_id),
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.handler_mode = "ai"
        conversation.needs_attention = False
        db.commit()

        try:
            await broadcaster.broadcast(
                hotel_id=request.account_id,
                event_type="handler_changed",
                data={
                    "conversation_id": str(conversation_id),
                    "handler_mode": "ai",
                    "needs_attention": False,
                },
            )
        except Exception as e:
            logger.warning(f"SSE broadcast failed (non-fatal): {e}")

        return {"success": True, "handler_mode": "ai", "needs_attention": False}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error returning to AI: {e}")
        raise HTTPException(status_code=500, detail="Failed to return to AI")


class CloseConversationRequest(BaseModel):
    account_id: str


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
            SMSConversation.account_id == UUID(request.account_id),
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
        logger.exception(f"Error closing conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to close conversation")


class MarkReadRequest(BaseModel):
    account_id: str


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
            SMSConversation.account_id == UUID(request.account_id),
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.last_read_at = datetime.utcnow()
        db.commit()
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error marking as read: {e}")
        raise HTTPException(status_code=500, detail="Failed to mark as read")


class PresenceRequest(BaseModel):
    account_id: str
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
            SMSConversation.account_id == UUID(request.account_id),
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
        logger.exception(f"Error setting presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to set presence")


class ClearPresenceRequest(BaseModel):
    account_id: str
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
            SMSConversation.account_id == UUID(request.account_id),
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
        logger.exception(f"Error clearing presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear presence")


class AgentReplyRequest(BaseModel):
    account_id: str
    message: str
    media_urls: Optional[List[str]] = None


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
            SMSConversation.account_id == UUID(request.account_id),
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
            account_id=conversation.account_id,
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

        attention_was_set = bool(conversation.needs_attention)
        if attention_was_set:
            conversation.needs_attention = False

        db.commit()

        account_id_str = str(conversation.account_id)
        conv_id_str    = str(conversation.id)

        try:
            await broadcaster.broadcast(
                hotel_id=account_id_str,
                event_type="new_reply",
                data={
                    "conversation_id": conv_id_str,
                    "customer_number": conversation.customer_number,
                    "preview": (message_text or "")[:100],
                    "account_id": account_id_str,
                },
            )
            if attention_was_set:
                await broadcaster.broadcast(
                    hotel_id=account_id_str,
                    event_type="handler_changed",
                    data={
                        "conversation_id": conv_id_str,
                        "handler_mode": "human",
                        "needs_attention": False,
                    },
                )
        except Exception as e:
            logger.warning(f"SSE broadcast failed (non-fatal): {e}")

        return {"success": True, "message": msg.to_dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error sending agent reply: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reply")


class GenerateSMSSummaryRequest(BaseModel):
    account_id: str


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
            SMSConversation.account_id == UUID(request.account_id),
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
            label = _SUMMARY_SENDER_LABEL.get(msg.sender, msg.sender.capitalize())
            transcript_text += f"{label}: {msg.content}\n"

        prompt = f"""Analyze this SMS conversation and provide:
1. A concise 2-3 sentence summary of what happened
2. Key points: customer intent, actions taken, and outcome

Note: "AI" = the automated assistant, "Agent" = a human support agent who took over.

SMS Conversation:
{transcript_text}

Respond in JSON format:
{{
    "summary": "...",
    "key_points": ["...", "..."]
}}"""

        response = _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a customer service analyst. "
                        "Provide clear, professional summaries of SMS conversations. "
                        "'AI' = automated assistant, 'Agent' = human support staff."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        result = json.loads(response.choices[0].message.content)
        summary    = result.get("summary", "")
        key_points = result.get("key_points", [])

        full_summary = summary
        if key_points:
            full_summary += "\n\nKey Points:\n" + "\n".join([f"- {p}" for p in key_points])

        conversation.ai_summary = full_summary
        db.commit()

        return {"success": True, "summary": full_summary}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating SMS summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")

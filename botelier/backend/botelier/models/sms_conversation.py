"""
SMSConversation and SMSMessage Models - Track SMS conversation history.

Multi-tenant isolation: All queries MUST filter by hotel_id to prevent data leakage.

SMSConversation represents a threaded conversation with a customer via SMS.
SMSMessage represents individual messages within a conversation.
"""

import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from botelier.database import Base


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    TRANSFERRED = "transferred"
    OPTED_OUT = "opted_out"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageSender(str, Enum):
    CUSTOMER = "customer"
    AI = "ai"
    AGENT = "agent"


class MessageStatus(str, Enum):
    RECEIVED = "received"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class SMSConversation(Base):
    """
    Represents a unified SMS conversation thread with a customer.

    One conversation per customer_number + botelier_number + hotel_id.
    Session boundaries are tracked on individual messages rather than
    splitting into separate conversations.
    """
    __tablename__ = "sms_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False)
    assistant_id = Column(UUID(as_uuid=True), ForeignKey("assistants.id"), nullable=True)
    phone_number_id = Column(UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True)

    customer_number = Column(String, nullable=False)
    botelier_number = Column(String, nullable=False)

    status = Column(String(20), nullable=False, default=ConversationStatus.ACTIVE.value)

    message_count = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    last_read_at = Column(DateTime, nullable=True)

    active_agent_id = Column(UUID(as_uuid=True), nullable=True)
    active_agent_name = Column(String, nullable=True)
    agent_active_at = Column(DateTime, nullable=True)

    disposition_id = Column(UUID(as_uuid=True), ForeignKey("assistant_dispositions.id"), nullable=True)
    ai_summary = Column(Text, nullable=True)
    tools_used = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    messages = relationship(
        "SMSMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="SMSMessage.created_at"
    )
    disposition = relationship("AssistantDisposition", foreign_keys=[disposition_id])

    __table_args__ = (
        Index('ix_sms_conv_hotel_status', 'hotel_id', 'status'),
        Index('ix_sms_conv_hotel_last_msg', 'hotel_id', 'last_message_at'),
        Index('ix_sms_conv_customer_number', 'hotel_id', 'customer_number', 'botelier_number'),
    )

    def __repr__(self):
        return f"<SMSConversation {self.customer_number} ({self.status})>"

    def to_dict(self, include_messages=False):
        result = {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "assistant_id": str(self.assistant_id) if self.assistant_id else None,
            "phone_number_id": str(self.phone_number_id) if self.phone_number_id else None,
            "customer_number": self.customer_number,
            "botelier_number": self.botelier_number,
            "status": self.status,
            "message_count": self.message_count,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "last_message_at": self.last_message_at.isoformat() + "Z" if self.last_message_at else None,
            "closed_at": self.closed_at.isoformat() + "Z" if self.closed_at else None,
            "last_read_at": self.last_read_at.isoformat() + "Z" if self.last_read_at else None,
            "has_unread": bool(self.last_message_at and (not self.last_read_at or self.last_message_at > self.last_read_at)),
            "disposition_id": str(self.disposition_id) if self.disposition_id else None,
            "disposition_name": self.disposition.name if self.disposition else None,
            "disposition_color": self.disposition.color if self.disposition else None,
            "active_agent_id": str(self.active_agent_id) if self.active_agent_id else None,
            "active_agent_name": self.active_agent_name,
            "agent_active_at": self.agent_active_at.isoformat() + "Z" if self.agent_active_at else None,
            "ai_summary": self.ai_summary,
            "tools_used": self.tools_used,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }

        if include_messages and self.messages:
            result["messages"] = [msg.to_dict() for msg in self.messages]

        return result


class SMSMessage(Base):
    """
    Represents a single SMS message within a conversation.
    """
    __tablename__ = "sms_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    conversation_id = Column(UUID(as_uuid=True), ForeignKey("sms_conversations.id", ondelete="CASCADE"), nullable=False)

    direction = Column(String(10), nullable=False)
    sender = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)

    media_urls = Column(JSONB, nullable=True)
    session_boundary = Column(Boolean, default=False, nullable=False)

    twilio_sid = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default=MessageStatus.RECEIVED.value)

    tokens_used = Column(Integer, nullable=True)
    tool_calls = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("SMSConversation", back_populates="messages")

    __table_args__ = (
        Index('ix_sms_msg_conversation', 'conversation_id', 'created_at'),
    )

    def __repr__(self):
        return f"<SMSMessage {self.direction} ({self.sender})>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "direction": self.direction,
            "sender": self.sender,
            "content": self.content,
            "media_urls": self.media_urls,
            "session_boundary": self.session_boundary,
            "twilio_sid": self.twilio_sid,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }

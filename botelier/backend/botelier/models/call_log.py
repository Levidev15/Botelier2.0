"""
CallLog and CallLeg Models - Track call history and transfer legs.

Multi-tenant isolation: All queries MUST filter by hotel_id to prevent data leakage.

CallLog represents a single incoming call to the hotel.
CallLeg represents individual segments of a call (AI conversation, transfers, etc.)
"""

import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Text, Index, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from botelier.database import Base


class CallStatus(str, Enum):
    """Status of a call."""
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    CANCELED = "canceled"


class CallOutcome(str, Enum):
    """What happened during the call."""
    BOOKING_MADE = "booking_made"
    INFO_PROVIDED = "info_provided"
    TRANSFERRED = "transferred"
    CALLBACK_REQUESTED = "callback_requested"
    ABANDONED = "abandoned"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class LegType(str, Enum):
    """Type of call leg."""
    AI_CONVERSATION = "ai_conversation"
    TRANSFER_EXTERNAL = "transfer_external"
    TRANSFER_SIP = "transfer_sip"
    TRANSFER_INTERNAL = "transfer_internal"
    TRANSFER_COLD = "transfer_cold"


class CallLog(Base):
    """
    CallLog model for tracking call history.
    
    SECURITY: Always filter by hotel_id to prevent cross-tenant data access.
    
    Each call log represents an incoming call and includes:
    - Call metadata (duration, timestamps, status)
    - Transcript of the conversation
    - Reference to phone number and assistant used
    - Recording URL if available
    """
    __tablename__ = "call_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    hotel_id = Column(UUID(as_uuid=True), ForeignKey("hotels.id"), nullable=False, index=True)
    
    reference_id = Column(String(8), nullable=True)

    call_sid = Column(String, unique=True, nullable=False)
    
    phone_number_id = Column(UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True)
    
    assistant_id = Column(UUID(as_uuid=True), ForeignKey("assistants.id"), nullable=True)
    
    caller_number = Column(String, nullable=True)
    
    to_number = Column(String, nullable=True)
    
    status = Column(String, default=CallStatus.INITIATED.value)
    outcome = Column(String, default=CallOutcome.UNKNOWN.value)
    
    started_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    
    duration_seconds = Column(Integer, default=0)
    
    transcript = Column(JSONB, nullable=True)
    
    recording_url = Column(String, nullable=True)
    recording_sid = Column(String, nullable=True)
    
    has_transfer = Column(Boolean, default=False)
    transfer_mode = Column(String, nullable=True)
    
    flow_id = Column(UUID(as_uuid=True), nullable=True)
    flow_name = Column(String, nullable=True)
    
    disposition_id = Column(UUID(as_uuid=True), ForeignKey("assistant_dispositions.id", ondelete="SET NULL"), nullable=True)
    ai_summary = Column(Text, nullable=True)
    
    acw_resolution = Column(String, nullable=True)
    acw_quality_score = Column(Integer, nullable=True)
    acw_completed_at = Column(DateTime, nullable=True)
    
    tool_name = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    
    legs = relationship("CallLeg", back_populates="call_log", cascade="all, delete-orphan", order_by="CallLeg.leg_number")
    disposition = relationship("AssistantDisposition", foreign_keys=[disposition_id])
    
    __table_args__ = (
        Index('ix_call_logs_hotel_started', 'hotel_id', 'started_at'),
        Index('ix_call_logs_hotel_status', 'hotel_id', 'status'),
    )
    
    def __repr__(self):
        return f"<CallLog {self.call_sid} ({self.status})>"
    
    def to_dict(self, include_legs=False, include_transcript=False):
        """Convert to dictionary for API responses."""
        result = {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "reference_id": self.reference_id,
            "call_sid": self.call_sid,
            "phone_number_id": str(self.phone_number_id) if self.phone_number_id else None,
            "assistant_id": str(self.assistant_id) if self.assistant_id else None,
            "caller_number": self.caller_number,
            "to_number": self.to_number,
            "status": self.status,
            "outcome": self.outcome,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "answered_at": self.answered_at.isoformat() + "Z" if self.answered_at else None,
            "ended_at": self.ended_at.isoformat() + "Z" if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "has_transfer": self.has_transfer,
            "flow_id": str(self.flow_id) if self.flow_id else None,
            "flow_name": self.flow_name,
            "recording_url": self.recording_url,
            "disposition_id": str(self.disposition_id) if self.disposition_id else None,
            "disposition_name": self.disposition.name if self.disposition else None,
            "disposition_color": self.disposition.color if self.disposition else None,
            "ai_summary": self.ai_summary,
            "acw_resolution": self.acw_resolution,
            "acw_quality_score": self.acw_quality_score,
            "acw_completed_at": self.acw_completed_at.isoformat() + "Z" if self.acw_completed_at else None,
            "tool_name": self.tool_name,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
        
        if include_transcript:
            result["transcript"] = self.transcript
        
        if include_legs and self.legs:
            result["legs"] = [leg.to_dict() for leg in self.legs]
        
        return result


@event.listens_for(CallLog, "init")
def _init_call_log_reference_id(target, args, kwargs):
    """Derive reference_id from the same UUID as id on object creation."""
    if not kwargs.get("reference_id"):
        uid = kwargs.get("id")
        if uid is None:
            uid = uuid.uuid4()
            kwargs["id"] = uid
        if not hasattr(uid, "hex"):
            uid = uuid.UUID(str(uid))
        kwargs["reference_id"] = uid.hex[:8].upper()


class CallLeg(Base):
    """
    CallLeg model for tracking individual segments of a call.
    
    When a call is transferred, each segment becomes a separate leg:
    - Leg 1: AI conversation (initial handling)
    - Leg 2: Transfer to external number or SIP
    - Leg 3: Further transfers if any
    
    This allows tracking billing for external transfers where
    costs continue until both parties hang up.
    """
    __tablename__ = "call_legs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    call_log_id = Column(UUID(as_uuid=True), ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    
    leg_number = Column(Integer, nullable=False)
    
    leg_type = Column(String, nullable=False)
    
    call_sid = Column(String, nullable=True)
    
    participant = Column(String, nullable=True)
    participant_name = Column(String, nullable=True)
    
    status = Column(String, default=CallStatus.INITIATED.value)
    
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    call_log = relationship("CallLog", back_populates="legs")
    
    __table_args__ = (
        Index('ix_call_legs_call_log', 'call_log_id', 'leg_number'),
    )
    
    def __repr__(self):
        return f"<CallLeg {self.leg_number} ({self.leg_type})>"
    
    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "call_log_id": str(self.call_log_id),
            "leg_number": self.leg_number,
            "leg_type": self.leg_type,
            "call_sid": self.call_sid,
            "participant": self.participant,
            "participant_name": self.participant_name,
            "status": self.status,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "ended_at": self.ended_at.isoformat() + "Z" if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }

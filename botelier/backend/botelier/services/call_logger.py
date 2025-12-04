"""
Call Logger Service - Centralized call log management.

This service handles all call log updates to avoid code duplication
across webhooks, WebSocket handlers, and other components.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from loguru import logger

from ..models import CallLog, CallLeg, CallStatus, CallOutcome, LegType


class CallLogger:
    """
    Centralized service for managing call log records.
    
    Handles:
    - Creating call logs and legs
    - Updating call status (from Twilio callbacks or WebSocket events)
    - Capturing transcripts from Pipecat conversations
    - Setting call outcomes based on conversation analysis
    """
    
    def __init__(self, db: Session):
        """Initialize with database session."""
        self.db = db
    
    def get_call_log(self, call_sid: str) -> Optional[CallLog]:
        """Get a call log by call SID."""
        return self.db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
    
    def update_status(
        self,
        call_sid: str,
        status: str,
        duration_seconds: Optional[int] = None
    ) -> bool:
        """
        Update call log status from Twilio callback or WebSocket event.
        
        Args:
            call_sid: Twilio call SID
            status: New status (initiated, ringing, in-progress, completed, etc.)
            duration_seconds: Call duration if available
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            status_mapping = {
                "initiated": CallStatus.INITIATED.value,
                "ringing": CallStatus.RINGING.value,
                "in-progress": CallStatus.IN_PROGRESS.value,
                "completed": CallStatus.COMPLETED.value,
                "busy": CallStatus.BUSY.value,
                "failed": CallStatus.FAILED.value,
                "no-answer": CallStatus.NO_ANSWER.value,
                "canceled": CallStatus.CANCELED.value,
            }
            
            new_status = status_mapping.get(status, status)
            call_log.status = new_status
            
            if status == "in-progress" and not call_log.answered_at:
                call_log.answered_at = datetime.utcnow()
            
            if status in ("completed", "busy", "failed", "no-answer", "canceled"):
                call_log.ended_at = datetime.utcnow()
                if duration_seconds is not None:
                    call_log.duration_seconds = duration_seconds
            
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            if ai_leg:
                ai_leg.status = new_status
                if status in ("completed", "busy", "failed", "no-answer", "canceled"):
                    ai_leg.ended_at = datetime.utcnow()
                    if duration_seconds is not None:
                        ai_leg.duration_seconds = duration_seconds
            
            self.db.commit()
            logger.info(f"Updated call {call_sid} status to {new_status}")
            return True
            
        except Exception as e:
            logger.exception(f"Error updating call status: {e}")
            self.db.rollback()
            return False
    
    def complete_call(
        self,
        call_sid: str,
        transcript: Optional[List[Dict[str, Any]]] = None,
        outcome: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ) -> bool:
        """
        Mark a call as completed and save transcript.
        
        This is typically called when the WebSocket connection closes
        or when Pipecat's pipeline ends.
        
        Args:
            call_sid: Twilio call SID
            transcript: List of conversation messages (role, content)
            outcome: Call outcome (booking_made, info_provided, transferred, etc.)
            duration_seconds: Total call duration
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            if call_log.status != CallStatus.COMPLETED.value:
                call_log.status = CallStatus.COMPLETED.value
            
            if not call_log.ended_at:
                call_log.ended_at = datetime.utcnow()
            
            if transcript:
                formatted_transcript = []
                for msg in transcript:
                    if msg.get("role") in ("user", "assistant"):
                        formatted_transcript.append({
                            "role": msg["role"],
                            "content": msg.get("content", ""),
                            "timestamp": datetime.utcnow().isoformat()
                        })
                call_log.transcript = formatted_transcript
                logger.info(f"Saved transcript with {len(formatted_transcript)} messages for call {call_sid}")
            
            if outcome:
                call_log.outcome = outcome
            elif not call_log.outcome or call_log.outcome == CallOutcome.UNKNOWN.value:
                call_log.outcome = CallOutcome.COMPLETED.value
            
            if duration_seconds is not None:
                call_log.duration_seconds = duration_seconds
            elif call_log.started_at and call_log.ended_at:
                call_log.duration_seconds = int((call_log.ended_at - call_log.started_at).total_seconds())
            
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            if ai_leg:
                ai_leg.status = CallStatus.COMPLETED.value
                if not ai_leg.ended_at:
                    ai_leg.ended_at = datetime.utcnow()
                if ai_leg.started_at and ai_leg.ended_at:
                    ai_leg.duration_seconds = int((ai_leg.ended_at - ai_leg.started_at).total_seconds())
            
            self.db.commit()
            logger.info(f"Completed call {call_sid} with outcome: {call_log.outcome}")
            return True
            
        except Exception as e:
            logger.exception(f"Error completing call: {e}")
            self.db.rollback()
            return False
    
    def record_transfer(
        self,
        call_sid: str,
        transfer_to: str,
        transfer_type: str = "external"
    ) -> bool:
        """
        Record that a call was transferred.
        
        Args:
            call_sid: Twilio call SID
            transfer_to: Phone number or SIP URI transferred to
            transfer_type: "external" or "sip"
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            call_log.has_transfer = True
            call_log.outcome = CallOutcome.TRANSFERRED.value
            
            max_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id
            ).order_by(CallLeg.leg_number.desc()).first()
            
            next_leg_num = (max_leg.leg_number + 1) if max_leg else 1
            
            leg_type = LegType.TRANSFER_SIP.value if transfer_type == "sip" else LegType.TRANSFER_EXTERNAL.value
            
            transfer_leg = CallLeg(
                call_log_id=call_log.id,
                leg_number=next_leg_num,
                leg_type=leg_type,
                participant=transfer_to,
                status=CallStatus.INITIATED.value,
                started_at=datetime.utcnow(),
            )
            self.db.add(transfer_leg)
            
            self.db.commit()
            logger.info(f"Recorded transfer for call {call_sid} to {transfer_to}")
            return True
            
        except Exception as e:
            logger.exception(f"Error recording transfer: {e}")
            self.db.rollback()
            return False

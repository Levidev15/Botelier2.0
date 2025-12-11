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
            
            # Mark the AI conversation leg as completed (transfer ends the AI portion)
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            if ai_leg and ai_leg.status != CallStatus.COMPLETED.value:
                ai_leg.status = CallStatus.COMPLETED.value
                ai_leg.ended_at = datetime.utcnow()
                if ai_leg.started_at and ai_leg.ended_at:
                    ai_leg.duration_seconds = int((ai_leg.ended_at - ai_leg.started_at).total_seconds())
                logger.info(f"Marked AI leg as completed (duration: {ai_leg.duration_seconds}s)")
            
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
    
    def update_leg_status(
        self,
        leg_call_sid: str,
        status: str,
        duration_seconds: Optional[int] = None,
        parent_call_sid: str = None,
        to_number: str = None,
    ) -> bool:
        """
        Update a specific call leg's status.
        
        Called when we receive status updates for transfer calls.
        
        Args:
            leg_call_sid: The call SID of the specific leg (the child/transfer call)
            status: New status (initiated, ringing, in-progress, completed, etc.)
            duration_seconds: Duration if available
            parent_call_sid: The original call's SID (to find the leg if call_sid not set)
            to_number: The number being called (to match leg by participant)
            
        Returns:
            True if update was successful
        """
        try:
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
            
            # First try to find leg by call_sid
            leg = self.db.query(CallLeg).filter(CallLeg.call_sid == leg_call_sid).first()
            
            # If not found, try to find by parent call + participant (transfer-to number)
            call_log = None
            if not leg and parent_call_sid and to_number:
                call_log = self.get_call_log(parent_call_sid)
                if call_log:
                    leg = self.db.query(CallLeg).filter(
                        CallLeg.call_log_id == call_log.id,
                        CallLeg.participant == to_number,
                        CallLeg.call_sid.is_(None),  # Leg created but not yet linked to child call
                    ).first()
                    
                    # If found, link the child call_sid to the leg
                    if leg:
                        leg.call_sid = leg_call_sid
                        logger.info(f"Linked child call {leg_call_sid} to transfer leg {leg.leg_number}")
            
            if not leg:
                logger.warning(f"Call leg not found for SID: {leg_call_sid}")
                return False
            
            leg.status = new_status
            
            # Mark in_progress when call is answered
            if status == "in-progress" and not leg.started_at:
                leg.started_at = datetime.utcnow()
            
            # Mark ended and calculate duration when call ends
            if status in ("completed", "busy", "failed", "no-answer", "canceled"):
                leg.ended_at = datetime.utcnow()
                if duration_seconds is not None:
                    leg.duration_seconds = duration_seconds
                elif leg.started_at and leg.ended_at:
                    leg.duration_seconds = int((leg.ended_at - leg.started_at).total_seconds())
                
                # When transfer leg ends (success or fail), mark parent call as completed
                if leg.leg_type in (LegType.TRANSFER_EXTERNAL.value, LegType.TRANSFER_SIP.value):
                    if not call_log and parent_call_sid:
                        call_log = self.get_call_log(parent_call_sid)
                    if not call_log:
                        call_log = self.db.query(CallLog).filter(CallLog.id == leg.call_log_id).first()
                    
                    if call_log and call_log.status != CallStatus.COMPLETED.value:
                        call_log.status = CallStatus.COMPLETED.value
                        call_log.ended_at = datetime.utcnow()
                        
                        # Set outcome based on transfer result
                        if status == "failed":
                            call_log.outcome = "transfer_failed"
                        elif status in ("busy", "no-answer", "canceled"):
                            call_log.outcome = f"transfer_{status.replace('-', '_')}"
                        # If completed successfully, keep "transferred" outcome
                        
                        if call_log.started_at and call_log.ended_at:
                            call_log.duration_seconds = int((call_log.ended_at - call_log.started_at).total_seconds())
                        
                        logger.info(f"Marked parent call {call_log.call_sid} as completed after transfer {status}")
            
            self.db.commit()
            logger.info(f"Updated leg {leg.leg_number} status to {new_status} (duration: {leg.duration_seconds}s)")
            return True
            
        except Exception as e:
            logger.exception(f"Error updating leg status: {e}")
            self.db.rollback()
            return False
    
    def create_transfer_leg_from_callback(
        self,
        parent_call_sid: str,
        child_call_sid: str,
        to_number: str,
        status: str
    ) -> bool:
        """
        Create a transfer leg when receiving a callback for a child call.
        
        This handles the case where Twilio sends us a callback for a child call
        created by the transfer, and we need to track it as a leg.
        
        Args:
            parent_call_sid: Original call SID
            child_call_sid: Transfer call SID
            to_number: Number being called
            status: Initial status
            
        Returns:
            True if created successfully
        """
        try:
            call_log = self.db.query(CallLog).filter(
                CallLog.call_sid == parent_call_sid
            ).first()
            
            if not call_log:
                logger.warning(f"Parent call log not found: {parent_call_sid}")
                return False
            
            existing_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.call_sid == child_call_sid
            ).first()
            
            if existing_leg:
                return True
            
            max_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id
            ).order_by(CallLeg.leg_number.desc()).first()
            
            next_leg_num = (max_leg.leg_number + 1) if max_leg else 1
            
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
            
            new_status = status_mapping.get(status, status) if status else CallStatus.INITIATED.value
            
            transfer_leg = CallLeg(
                call_log_id=call_log.id,
                leg_number=next_leg_num,
                leg_type=LegType.TRANSFER_EXTERNAL.value,
                call_sid=child_call_sid,
                participant=to_number,
                status=new_status,
                started_at=datetime.utcnow(),
            )
            self.db.add(transfer_leg)
            
            call_log.has_transfer = True
            
            self.db.commit()
            logger.info(f"Created transfer leg {next_leg_num} for call {parent_call_sid}")
            return True
            
        except Exception as e:
            logger.exception(f"Error creating transfer leg: {e}")
            self.db.rollback()
            return False
    
    def has_transfer(self, call_sid: str) -> bool:
        """Check if a call has an active transfer."""
        call_log = self.get_call_log(call_sid)
        return bool(call_log and call_log.has_transfer)

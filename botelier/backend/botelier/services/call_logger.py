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
                if not call_log.ended_at:
                    call_log.ended_at = datetime.utcnow()
                # For transferred calls, duration is finalized by update_leg_status
                # after the transfer leg ends. Avoid overwriting it here with a
                # wall-clock value that may not yet include the transfer time.
                if not call_log.has_transfer and call_log.started_at and call_log.ended_at:
                    call_log.duration_seconds = int(
                        (call_log.ended_at - call_log.started_at).total_seconds()
                    )
            
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            if ai_leg:
                ai_leg.status = new_status
                if status in ("completed", "busy", "failed", "no-answer", "canceled"):
                    if not ai_leg.ended_at:
                        ai_leg.ended_at = datetime.utcnow()
                    if ai_leg.started_at:
                        ai_leg.duration_seconds = int((ai_leg.ended_at - ai_leg.started_at).total_seconds())
            
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
        duration_seconds: Optional[int] = None,
        tools_used: Optional[List[str]] = None
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
            
            if transcript and not call_log.transcript:
                # Only write transcript if one is not already stored.
                # Transfer calls save the transcript (including the spoken pre-transfer
                # message) inside _execute_transfer, BEFORE the pipeline shuts down.
                # The post-pipeline save in handle_call would overwrite that enriched
                # transcript with a version that lacks the pre-transfer line, so we
                # skip it here when the transcript has already been persisted.
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
            elif transcript and call_log.transcript:
                logger.info(f"Transcript already saved for call {call_sid} — skipping overwrite ({len(call_log.transcript)} messages preserved)")
            
            if outcome:
                call_log.outcome = outcome
            elif not call_log.outcome or call_log.outcome == CallOutcome.UNKNOWN.value:
                call_log.outcome = CallOutcome.COMPLETED.value
            
            if tools_used:
                call_log.tool_name = ", ".join(tools_used)
                logger.info(f"Saved tools used for call {call_sid}: {call_log.tool_name}")
            
            if duration_seconds is not None:
                call_log.duration_seconds = duration_seconds
            elif call_log.started_at and call_log.ended_at:
                call_log.duration_seconds = int((call_log.ended_at - call_log.started_at).total_seconds())
            
            # Update all legs when call ends
            all_legs = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id
            ).all()
            
            non_terminal_statuses = [
                CallStatus.INITIATED.value,
                CallStatus.RINGING.value,
                CallStatus.IN_PROGRESS.value,
            ]
            
            for leg in all_legs:
                # Only change status for legs in non-terminal states
                if leg.status in non_terminal_statuses:
                    leg.status = CallStatus.COMPLETED.value
                
                # For warm transfer legs, update end time to match call end time
                if leg.leg_type in (LegType.TRANSFER_EXTERNAL.value, LegType.TRANSFER_SIP.value):
                    if call_log.ended_at and (not leg.ended_at or leg.ended_at < call_log.ended_at):
                        leg.ended_at = call_log.ended_at
                        if leg.started_at:
                            leg.duration_seconds = int((leg.ended_at - leg.started_at).total_seconds())
                # Cold transfer legs are already marked completed — leave duration as-is (None = unknown)
                elif leg.leg_type == LegType.TRANSFER_COLD.value:
                    pass
                # For other legs, just ensure they have an end time
                elif not leg.ended_at:
                    leg.ended_at = call_log.ended_at or datetime.utcnow()
                    if leg.started_at:
                        leg.duration_seconds = int((leg.ended_at - leg.started_at).total_seconds())
            
            # Calculate total duration by summing all leg durations.
            # Cold transfer legs are excluded (duration unknown — Twilio exited the bridge).
            warm_legs = [leg for leg in all_legs if leg.leg_type != LegType.TRANSFER_COLD.value]
            total_leg_duration = sum(leg.duration_seconds or 0 for leg in warm_legs)
            if total_leg_duration > 0:
                call_log.duration_seconds = total_leg_duration
            
            self.db.commit()
            logger.info(f"Completed call {call_sid} with outcome: {call_log.outcome}")
            return True
            
        except Exception as e:
            logger.exception(f"Error completing call: {e}")
            self.db.rollback()
            return False
    
    def record_tool_usage(
        self,
        call_sid: str,
        tool_name: str,
        is_flow: bool = False
    ) -> bool:
        """
        Record that a tool or flow was used during a call.
        
        Args:
            call_sid: Twilio call SID
            tool_name: Name of the tool or flow
            is_flow: True if this is a flow, False if a regular tool
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            # Store tool/flow name (first tool takes precedence)
            if is_flow:
                if not call_log.flow_name:
                    call_log.flow_name = tool_name
            else:
                if not call_log.tool_name:
                    call_log.tool_name = tool_name
            
            self.db.commit()
            logger.info(f"Recorded {'flow' if is_flow else 'tool'} usage: {tool_name} for call {call_sid}")
            return True
            
        except Exception as e:
            logger.exception(f"Error recording tool usage: {e}")
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
            transfer_type: "external", "sip", or "cold"
                - "external": warm Twilio-bridged transfer to PSTN number
                - "sip": warm Twilio-bridged transfer via SIP
                - "cold": cold SIP REFER transfer — Twilio exits bridge immediately,
                          no status callbacks will arrive, leg is pre-marked completed
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            if transfer_type == "cold":
                leg_type = LegType.TRANSFER_COLD.value
            elif transfer_type == "sip":
                leg_type = LegType.TRANSFER_SIP.value
            else:
                leg_type = LegType.TRANSFER_EXTERNAL.value
            
            existing_transfer = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == leg_type,
                CallLeg.participant == transfer_to
            ).first()
            
            if existing_transfer:
                logger.info(f"Transfer leg to {transfer_to} already exists for call {call_sid}, skipping duplicate")
                return True
            
            call_log.has_transfer = True
            call_log.outcome = CallOutcome.TRANSFERRED.value
            call_log.transfer_mode = "cold" if transfer_type == "cold" else "warm"
            
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
            
            now = datetime.utcnow()
            
            if transfer_type == "cold":
                # Cold transfer: Twilio exits immediately — no callbacks will arrive.
                # Pre-mark the leg as completed with null duration (duration is unknown).
                transfer_leg = CallLeg(
                    call_log_id=call_log.id,
                    leg_number=next_leg_num,
                    leg_type=leg_type,
                    participant=transfer_to,
                    status=CallStatus.COMPLETED.value,
                    started_at=now,
                    ended_at=now,
                    duration_seconds=None,
                )
            else:
                # Warm transfer: Twilio stays in bridge, status callbacks will arrive.
                transfer_leg = CallLeg(
                    call_log_id=call_log.id,
                    leg_number=next_leg_num,
                    leg_type=leg_type,
                    participant=transfer_to,
                    status=CallStatus.INITIATED.value,
                    started_at=now,
                )
            
            self.db.add(transfer_leg)
            
            self.db.commit()
            logger.info(f"Recorded {transfer_type} transfer for call {call_sid} to {transfer_to}")
            return True
            
        except Exception as e:
            logger.exception(f"Error recording transfer: {e}")
            self.db.rollback()
            return False
    
    def complete_cold_transfer(self, call_sid: str) -> bool:
        """
        Finalize a cold-transferred call log.
        
        Called from /connect-complete when transfer_mode='cold'. Since Twilio exits
        the bridge immediately on a SIP REFER, no /transfer-status callbacks arrive.
        We finalize the call here using the AI leg duration as the tracked duration.
        
        Args:
            call_sid: Twilio call SID
            
        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False
            
            now = datetime.utcnow()
            
            if call_log.status != CallStatus.COMPLETED.value:
                call_log.status = CallStatus.COMPLETED.value
            
            if not call_log.ended_at:
                call_log.ended_at = now
            
            # Use AI leg duration as the logged call duration (transfer leg duration is unknown)
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            ai_duration = ai_leg.duration_seconds if ai_leg else 0
            if call_log.duration_seconds is None or call_log.duration_seconds == 0:
                call_log.duration_seconds = ai_duration or 0
            
            self.db.commit()
            logger.info(f"Finalized cold transfer call {call_sid} (AI leg duration: {ai_duration}s)")
            return True
            
        except Exception as e:
            logger.exception(f"Error finalizing cold transfer call: {e}")
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
                # Always calculate duration from our tracked start time (includes ringing)
                # Ignore Twilio's duration_seconds as it only counts from answer
                if leg.started_at and leg.ended_at:
                    leg.duration_seconds = int((leg.ended_at - leg.started_at).total_seconds())
                
                # When transfer leg ends (success or fail), update parent call.
                if leg.leg_type in (LegType.TRANSFER_EXTERNAL.value, LegType.TRANSFER_SIP.value):
                    if not call_log and parent_call_sid:
                        call_log = self.get_call_log(parent_call_sid)
                    if not call_log:
                        call_log = self.db.query(CallLog).filter(CallLog.id == leg.call_log_id).first()
                    
                    if call_log:
                        # Only update status/outcome if not already marked complete.
                        if call_log.status != CallStatus.COMPLETED.value:
                            call_log.status = CallStatus.COMPLETED.value
                            # Set outcome based on transfer result
                            if status == "failed":
                                call_log.outcome = "transfer_failed"
                            elif status in ("busy", "no-answer", "canceled"):
                                call_log.outcome = f"transfer_{status.replace('-', '_')}"
                            # If completed successfully, keep "transferred" outcome
                            logger.info(f"Marked parent call {call_log.call_sid} as completed after transfer {status}")
                        
                        # ALWAYS update ended_at and duration to include transfer time,
                        # even if the call was already marked completed by a parallel
                        # parent-call status callback. Using sum-of-legs ensures we never
                        # under-count when callbacks arrive out of order.
                        call_log.ended_at = leg.ended_at or datetime.utcnow()
                        all_legs = self.db.query(CallLeg).filter(
                            CallLeg.call_log_id == call_log.id
                        ).all()
                        non_cold = [l for l in all_legs if l.leg_type != LegType.TRANSFER_COLD.value]
                        total_dur = sum(l.duration_seconds or 0 for l in non_cold)
                        if total_dur > 0:
                            call_log.duration_seconds = total_dur
                        elif call_log.started_at and call_log.ended_at:
                            call_log.duration_seconds = int(
                                (call_log.ended_at - call_log.started_at).total_seconds()
                            )
            
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
            
            # Use the AI leg's ended_at as the transfer leg's start time
            # This captures the ringing/bridging time that would otherwise be lost
            ai_leg = self.db.query(CallLeg).filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type == LegType.AI_CONVERSATION.value
            ).first()
            
            transfer_started_at = datetime.utcnow()
            if ai_leg and ai_leg.ended_at:
                transfer_started_at = ai_leg.ended_at
            elif call_log.answered_at:
                transfer_started_at = call_log.answered_at
            
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
                started_at=transfer_started_at,
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

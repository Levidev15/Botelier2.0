"""
Call Logger Service - Centralized call log management.

This service handles all call log updates to avoid code duplication
across webhooks, WebSocket handlers, and other components.
"""

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from loguru import logger

from ..models import CallLog, CallLeg, CallStatus, CallOutcome, LegType
from ..models.call_event import CallEvent


# Vocabulary for forced-finalization sources. Kept aligned with Task #96.
# Any new source must be documented here so dashboards/analytics can surface it.
_FORCED_BY_SOURCES = {"sweeper", "webhook_safety_net", "finally_defensive", "shutdown"}

# Task #123 — the int4 clamp that lived here is gone. The
# call_events.offset_ms column is BIGINT (verified by the startup invariant
# in database._assert_call_events_offset_ms_bigint), so writers compute the
# true offset via services._event_offset.compute_offset_ms with no clamp.
# The legacy _INT4_MAX constant has been removed; nothing in the codebase
# imports it any more.


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

    def mark_greeting_completed(self, call_sid: str) -> bool:
        """
        Mark ai_greeting_completed=True on the call log.

        Called when the greeting TTS finishes playing (GreetingCompletionTracker).
        This is the reliable source of truth for whether the AI actually spoke to
        the caller — used later to classify calls as completed vs ended_early.
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"mark_greeting_completed: call log not found for {call_sid}")
                return False
            call_log.ai_greeting_completed = True
            # Race-condition guard: the Twilio status webhook may have arrived and
            # set status=ended_early before this pipeline callback fired (webhook sees
            # ai_greeting_completed=FALSE in the brief window before we commit here).
            # Since the greeting DID play, correct the status in the same transaction.
            if call_log.status == CallStatus.ENDED_EARLY.value:
                call_log.status = CallStatus.COMPLETED.value
                call_log.ended_early = False
                logger.info(f"Race correction: {call_sid} ended_early → completed (greeting confirmed)")
            self.db.commit()
            logger.info(f"ai_greeting_completed=True for {call_sid}")
            return True
        except Exception as e:
            logger.exception(f"Error marking greeting completed: {e}")
            self.db.rollback()
            return False

    def mark_caller_spoke(self, call_sid: str) -> bool:
        """
        Task #98 — set caller_spoke=True on first observed user utterance.

        Called from Pipecat's FirstUserSpeechTracker the first time a
        UserStartedSpeakingFrame (or transcription) is seen for the call.
        Idempotent: a second invocation is a no-op.

        Distinct from `ai_greeting_completed` which only proves the AI spoke;
        this proves the *caller* spoke, which is what guards the AI Handled
        bucket against silent-line greet-and-hangup mis-classification.
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"mark_caller_spoke: call log not found for {call_sid}")
                return False
            if call_log.caller_spoke is True:
                return True  # idempotent
            call_log.caller_spoke = True
            self.db.commit()
            logger.info(f"caller_spoke=True for {call_sid}")
            return True
        except Exception as e:
            logger.exception(f"Error marking caller_spoke: {e}")
            self.db.rollback()
            return False

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
                "ended_early": CallStatus.ENDED_EARLY.value,
                "busy": CallStatus.BUSY.value,
                "failed": CallStatus.FAILED.value,
                "no-answer": CallStatus.NO_ANSWER.value,
                "canceled": CallStatus.CANCELED.value,
            }
            
            new_status = status_mapping.get(status, status)
            call_log.status = new_status
            
            if status == "in-progress" and not call_log.answered_at:
                answer_time = datetime.utcnow()
                call_log.answered_at = answer_time
                # Reset the AI leg's started_at to the true answer time so the AI leg
                # duration reflects only the actual conversation, not pre-answer setup.
                ai_leg_for_answer = self.db.query(CallLeg).filter(
                    CallLeg.call_log_id == call_log.id,
                    CallLeg.leg_type == LegType.AI_CONVERSATION.value
                ).first()
                if ai_leg_for_answer and ai_leg_for_answer.status not in (
                    CallStatus.COMPLETED.value,
                    CallStatus.FAILED.value,
                    CallStatus.BUSY.value,
                    CallStatus.NO_ANSWER.value,
                    CallStatus.CANCELED.value,
                ):
                    ai_leg_for_answer.started_at = answer_time

            if status in ("completed", "busy", "failed", "no-answer", "canceled"):
                if not call_log.ended_at:
                    call_log.ended_at = datetime.utcnow()
                # For transferred calls, duration is finalized by update_leg_status
                # after the transfer leg ends. Avoid overwriting it here with a
                # wall-clock value that may not yet include the transfer time.
                if not call_log.has_transfer:
                    if duration_seconds is not None:
                        # Twilio's CallDuration is authoritative: talk time only
                        # (answer → hangup), excludes ring time.
                        call_log.duration_seconds = duration_seconds
                    elif call_log.answered_at and call_log.ended_at:
                        # answered_at → ended_at matches Twilio's CallDuration
                        # measurement and excludes ring time.
                        call_log.duration_seconds = max(0, int(
                            (call_log.ended_at - call_log.answered_at).total_seconds()
                        ))
                    elif call_log.started_at and call_log.ended_at:
                        # Last resort: includes ring time, but better than nothing.
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
                    # Use answered_at as the conversation anchor if available; it was
                    # already written to started_at during the in-progress callback, but
                    # guard with answered_at again for robustness. Clamp to 0.
                    anchor = call_log.answered_at if call_log.answered_at else ai_leg.started_at
                    if anchor and ai_leg.ended_at:
                        ai_leg.duration_seconds = max(0, int((ai_leg.ended_at - anchor).total_seconds()))
            
            self.db.commit()
            logger.info(f"Updated call {call_sid} status to {new_status}")
            return True
            
        except Exception as e:
            logger.exception(f"Error updating call status: {e}")
            self.db.rollback()
            return False
    
    def _write_event_inline(
        self,
        call_log_id,
        event_type: str,
        event_source: str,
        severity: str,
        details: Dict[str, Any],
        call_started_at: Optional[datetime],
    ) -> None:
        """
        Direct, non-queued CallEvent insert using ``self.db``.

        Safe to call from finalization paths where the per-call
        ``CallEventQueue`` has already been flushed/stopped (sweeper,
        webhook safety-net, defensive finally). Non-fatal on error —
        observability is best-effort and must never block a disposition.
        """
        try:
            # Task #123 — single offset_ms helper (no more int4 clamp; the
            # column is BIGINT and the startup invariant proves it).
            from ._event_offset import compute_offset_ms
            now = datetime.utcnow()
            offset_ms = compute_offset_ms(now, call_started_at)
            evt = CallEvent(
                id=uuid.uuid4(),
                call_log_id=call_log_id,
                event_type=event_type,
                event_source=event_source,
                severity=severity,
                occurred_at=now,
                offset_ms=offset_ms,
                details=details,
            )
            self.db.add(evt)
            # Intentionally not committing here; the caller batches the commit
            # with the CallLog mutation.
        except Exception as e:
            logger.warning(f"Failed to enqueue inline CallEvent {event_type}: {e}")

    @staticmethod
    def _write_event_isolated(
        call_log_id,
        event_type: str,
        event_source: str,
        severity: str,
        details: Dict[str, Any],
        call_started_at: Optional[datetime],
    ) -> None:
        """Task #123 — write a CallEvent in a fresh short-lived session.

        Used by ``complete_call`` for finalization-observability events
        (``finalization_forced``, ``call_ended``) so a failure on the event
        INSERT cannot roll back the surrounding CallLog status/ended_at
        mutation. The docstring on ``_write_event_inline`` claimed
        observability is "best-effort and must never block a disposition" —
        this is the implementation that actually honors that contract.

        Never raises; on error the event is logged and dropped, leaving the
        terminal-state mutation that already committed in place.
        """
        from ._event_offset import compute_offset_ms

        now = datetime.utcnow()
        offset_ms = compute_offset_ms(now, call_started_at)

        db = None
        try:
            # Import + SessionLocal() inside the try so a connection-acquisition
            # failure (pool exhaustion, DB unreachable) is swallowed too —
            # observability-helper guarantees never-raises end-to-end.
            from ..database import SessionLocal
            db = SessionLocal()
            evt = CallEvent(
                id=uuid.uuid4(),
                call_log_id=call_log_id,
                event_type=event_type,
                event_source=event_source,
                severity=severity,
                occurred_at=now,
                offset_ms=offset_ms,
                details=details,
            )
            db.add(evt)
            db.commit()
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(
                f"_write_event_isolated: failed to write {event_type} for "
                f"call_log {call_log_id} (non-fatal): {e}"
            )
        finally:
            try:
                db.close()
            except Exception:
                pass

    def complete_call(
        self,
        call_sid: str,
        transcript: Optional[List[Dict[str, Any]]] = None,
        outcome: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        tools_used: Optional[List[str]] = None,
        forced_by: Optional[str] = None,
        sweeper_age_seconds: Optional[int] = None,
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
            forced_by: When set, this call originated from a safety-net path
                (sweeper / webhook_safety_net / finally_defensive) rather than
                the normal pipeline teardown. Triggers emission of a
                ``finalization_forced`` CallEvent whose ``details.source``
                carries the reason — used for leak-rate observability.
            sweeper_age_seconds: Age of the stuck row when the sweeper picked it
                up, in seconds. Included in the emitted event details. Ignored
                unless ``forced_by == "sweeper"``.

        Returns:
            True if update was successful
        """
        try:
            call_log = self.get_call_log(call_sid)
            if not call_log:
                logger.warning(f"Call log not found for SID: {call_sid}")
                return False

            prior_status = call_log.status
            _terminal = {
                CallStatus.COMPLETED.value,
                CallStatus.ENDED_EARLY.value,
                CallStatus.FAILED.value,
                CallStatus.BUSY.value,
                CallStatus.NO_ANSWER.value,
                CallStatus.CANCELED.value,
            }
            # Idempotency for forced paths: if a safety-net path is invoked
            # against a row that is already in a terminal state AND already
            # has an ended_at, there is no work to do and NO finalization_forced
            # event is emitted. The event signals *real* safety-net usage
            # (i.e. this call path actually performed the terminal transition),
            # so emitting on a no-op would inflate the leak-rate dashboard
            # with healthy calls where a later Twilio retry raced a clean
            # finalization. Silent no-op is the right semantics here.
            if forced_by and prior_status in _terminal and call_log.ended_at is not None:
                logger.debug(
                    f"complete_call(forced_by={forced_by}) silent no-op for {call_sid}: "
                    f"already terminal ({prior_status}) with ended_at set"
                )
                return True

            # Determine terminal status: completed if AI greeted, ended_early otherwise.
            # Only override if the call is not already in a terminal state.
            _non_terminal = {CallStatus.INITIATED.value, CallStatus.RINGING.value, CallStatus.IN_PROGRESS.value}
            if call_log.status in _non_terminal:
                if call_log.ai_greeting_completed:
                    call_log.status = CallStatus.COMPLETED.value
                else:
                    call_log.status = CallStatus.ENDED_EARLY.value
                    call_log.ended_early = True
            elif call_log.status == CallStatus.COMPLETED.value and not call_log.ai_greeting_completed:
                # Reclassify: Twilio said completed but greeting never played.
                call_log.status = CallStatus.ENDED_EARLY.value
                call_log.ended_early = True

            # Task #98 — forward-only silent-caller stamp.
            # If Pipecat's FirstUserSpeechTracker never fired mark_caller_spoke()
            # by the time the call reaches its terminal state, the caller
            # produced no audio — record FALSE so analytics can route the row
            # into the unresolved bucket. This branch only executes for calls
            # processed by post-deploy code, so legacy rows (which were stamped
            # by older complete_call() before this column existed) remain NULL
            # and continue to count as ai_handled — preserving historical
            # metrics without a backfill.
            if call_log.caller_spoke is None:
                call_log.caller_spoke = False

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
                        entry: dict = {
                            "role": msg["role"],
                            "content": msg.get("content", ""),
                        }
                        # Preserve existing timestamp if set by the capture layer.
                        # Do NOT overwrite with datetime.utcnow() — doing so stamps
                        # every message with the same save-time, making timestamps
                        # meaningless.
                        if msg.get("timestamp"):
                            entry["timestamp"] = msg["timestamp"]
                        if msg.get("interrupted"):
                            entry["interrupted"] = True
                        if msg.get("incomplete"):
                            entry["incomplete"] = True
                        formatted_transcript.append(entry)
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
            
            # When the sweeper closes a call that never answered, the real call
            # duration is unknown — we must not fabricate it as (now - started_at).
            # All other paths (normal pipeline teardown, webhook safety-net, or
            # sweeper on a call that DID answer) compute duration as normal.
            _skip_sweeper_duration = forced_by == "sweeper" and not call_log.answered_at

            if duration_seconds is not None:
                call_log.duration_seconds = duration_seconds
            elif call_log.answered_at and call_log.ended_at:
                # answered_at → ended_at matches Twilio's CallDuration measurement
                # (excludes ring time). answered_at is always set after Task #40.
                call_log.duration_seconds = max(0, int(
                    (call_log.ended_at - call_log.answered_at).total_seconds()
                ))
            elif call_log.started_at and call_log.ended_at and not _skip_sweeper_duration:
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
                # For other legs (primarily ai_conversation), just ensure they have
                # an end time and an accurate duration.
                elif not leg.ended_at:
                    leg.ended_at = call_log.ended_at or datetime.utcnow()
                    # When the sweeper closes an unanswered call, the real duration is
                    # unknown — do not fabricate it as (now - started_at). Leave
                    # leg.duration_seconds at its existing value (typically 0).
                    if not _skip_sweeper_duration:
                        if leg.leg_type == LegType.AI_CONVERSATION.value:
                            # Use answered_at as the anchor — matches media stream billing
                            # and is consistent with update_status(). answered_at is always
                            # set after Task #40; fall back to started_at for safety.
                            anchor = call_log.answered_at or leg.started_at
                            if anchor:
                                leg.duration_seconds = max(0, int(
                                    (leg.ended_at - anchor).total_seconds()
                                ))
                        elif leg.started_at:
                            leg.duration_seconds = int((leg.ended_at - leg.started_at).total_seconds())
            
            # Calculate total duration by summing all leg durations.
            # Cold transfer legs are excluded (duration unknown — Twilio exited the bridge).
            warm_legs = [leg for leg in all_legs if leg.leg_type != LegType.TRANSFER_COLD.value]
            total_leg_duration = sum(leg.duration_seconds or 0 for leg in warm_legs)
            if total_leg_duration > 0:
                call_log.duration_seconds = total_leg_duration

            # Task #123 — observability events for safety-net finalizations.
            #
            # Previously these were appended to ``self.db`` and committed in
            # the same transaction as the CallLog status/ended_at mutation.
            # If the event INSERT failed at commit time (FK race, schema drift,
            # constraint violation) the entire transaction rolled back and the
            # CallLog row stayed stuck in its pre-finalize state — exactly the
            # bug the sweeper exists to prevent.
            #
            # We now collect the event payloads, commit the terminal-state
            # mutation FIRST, and then write the events through a fresh
            # short-lived session via _write_event_isolated. That helper
            # never raises; an event-write failure now logs a warning and
            # leaves the disposition committed.
            forced_event_payloads: list[Dict[str, Any]] = []
            if forced_by:
                if forced_by not in _FORCED_BY_SOURCES:
                    logger.warning(
                        f"complete_call: unknown forced_by value '{forced_by}' for {call_sid} "
                        f"— event will still be written"
                    )
                details: Dict[str, Any] = {
                    "source": forced_by,
                    "prior_status": prior_status,
                    "final_status": call_log.status,
                    "ai_greeting_completed": bool(call_log.ai_greeting_completed),
                }
                if forced_by == "sweeper" and sweeper_age_seconds is not None:
                    details["sweeper_age_seconds"] = int(sweeper_age_seconds)
                forced_event_payloads.append({
                    "event_type": "finalization_forced",
                    "severity": "warning",
                    "details": details,
                })
                # Also emit a call_ended event if one has not already been
                # written — so a sweeper-closed call still has a complete
                # timeline for the event-log modal.
                has_call_ended = (
                    self.db.query(CallEvent.id)
                    .filter(
                        CallEvent.call_log_id == call_log.id,
                        CallEvent.event_type == "call_ended",
                    )
                    .first()
                    is not None
                )
                if not has_call_ended:
                    _call_ended_details: Dict[str, Any] = {
                        "source": forced_by,
                        "end_reason": "finalized_by_sweeper" if forced_by == "sweeper" else "finalized_by_safety_net",
                        "ended_by": "system",
                    }
                    if forced_by == "sweeper" and sweeper_age_seconds is not None:
                        _call_ended_details["sweeper_age_seconds"] = int(sweeper_age_seconds)
                    forced_event_payloads.append({
                        "event_type": "call_ended",
                        "severity": "warning",
                        "details": _call_ended_details,
                    })

            # Capture the values needed by the post-commit event writes
            # before commit() expires the ORM attributes on call_log.
            _call_log_id = call_log.id
            _call_started_at = call_log.started_at

            self.db.commit()

            # Post-commit, isolated, never-raises event writes (Task #123).
            # Belt-and-suspenders: even though _write_event_isolated has its
            # own try/except, wrap the loop so a regression there cannot
            # propagate up and convert a successful disposition into a False
            # return value.
            for payload in forced_event_payloads:
                try:
                    self._write_event_isolated(
                        call_log_id=_call_log_id,
                        event_type=payload["event_type"],
                        event_source="app",
                        severity=payload["severity"],
                        details=payload["details"],
                        call_started_at=_call_started_at,
                    )
                except Exception as e:
                    logger.warning(
                        f"complete_call: post-commit event '{payload['event_type']}' "
                        f"emission failed (non-fatal, disposition already committed): {e}"
                    )

            logger.info(
                f"Completed call {call_sid} with outcome: {call_log.outcome}"
                + (f" (forced_by={forced_by})" if forced_by else "")
            )
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
                # Prefer answered_at as the conversation start anchor to exclude pre-answer setup.
                # This value will be recalculated again in update_leg_status once the
                # transfer leg duration is authoritative (Task 3), so this is a best-effort
                # intermediate value.
                anchor = call_log.answered_at if call_log.answered_at else ai_leg.started_at
                if anchor and ai_leg.ended_at:
                    ai_leg.duration_seconds = max(0, int((ai_leg.ended_at - anchor).total_seconds()))
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
                # Prefer Twilio's authoritative CallDuration for transfer/outbound legs.
                # Twilio measures from the moment the called party answers to hang-up,
                # which is the billable duration and avoids server clock drift issues.
                # Fall back to wall-clock arithmetic only when Twilio doesn't provide it,
                # and clamp to zero to prevent negative values from clock skew.
                if duration_seconds is not None:
                    leg.duration_seconds = duration_seconds
                elif leg.started_at and leg.ended_at:
                    leg.duration_seconds = max(0, int((leg.ended_at - leg.started_at).total_seconds()))

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

                        # Recalculate AI leg duration now that transfer leg is authoritative.
                        # Use answered_at -> ai_leg.ended_at for the most accurate value.
                        # This corrects any drift introduced before the in-progress anchor.
                        ai_leg_final = next(
                            (l for l in all_legs if l.leg_type == LegType.AI_CONVERSATION.value),
                            None,
                        )
                        if ai_leg_final and ai_leg_final.ended_at:
                            if call_log.answered_at:
                                corrected = max(0, int(
                                    (ai_leg_final.ended_at - call_log.answered_at).total_seconds()
                                ))
                                ai_leg_final.duration_seconds = corrected
                                logger.info(
                                    f"Recalculated AI leg duration to {corrected}s "
                                    f"(answered_at -> ai_leg.ended_at)"
                                )
                            elif ai_leg_final.started_at:
                                corrected = max(0, int(
                                    (ai_leg_final.ended_at - ai_leg_final.started_at).total_seconds()
                                ))
                                ai_leg_final.duration_seconds = corrected

                        total_dur = sum(l.duration_seconds or 0 for l in non_cold)
                        if total_dur > 0:
                            call_log.duration_seconds = total_dur
                        elif call_log.answered_at and call_log.ended_at:
                            # answered_at → ended_at excludes ring time and matches
                            # Twilio's CallDuration measurement.
                            call_log.duration_seconds = max(0, int(
                                (call_log.ended_at - call_log.answered_at).total_seconds()
                            ))
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

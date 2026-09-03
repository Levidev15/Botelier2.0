"""Function Mapper - Converts database tools to Pipecat function calls.

This module bridges the gap between hotel-configured tools in the database
and the actual Pipecat function calling system during voice conversations.
"""

import asyncio
import os
import re as _re_tool_name
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from loguru import logger

from ..config.domain import get_public_base_url
from ..logging_config import should_log_prompts as _should_log_prompts
from ..utils import sanitize_function_name

if TYPE_CHECKING:
    from .call_handler import CallHandler
from twilio.base.exceptions import TwilioRestException as _TwilioRestException
from twilio.rest import Client as TwilioClient

from botelier.flow_executor import (
    CallFlowContext,
    NodeType,
    FlowExecutor,
    parse_flow_config,
    substitute_variables,
)
from botelier.models.tool import Tool, ToolType
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import EndFrame, FunctionCallResultProperties, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams


# Maximum time to wait for Twilio's playback mark acknowledgement before
# continuing a transfer or hangup. The timeout is a safety net; a missing mark
# should not strand a caller, but a received mark proves the configured phrase
# fully played.  The mark is only sent AFTER BotStoppedSpeakingFrame, so the
# remaining wait covers Twilio's outbound jitter buffer (typically a few
# seconds of tail audio) — 2 s was too tight and clipped the end of longer
# messages; 10 s comfortably covers the buffer without stranding anyone.
TWILIO_MARK_TIMEOUT_SECS: float = 10.0

# Conservative speech-rate assumptions for estimating how long a phrase takes
# to play at 8 kHz telephony rates.  Used ONLY on degraded paths (missing mark
# watcher, mark-ack timeout, no completion watcher) where we cannot confirm
# playback and must wait a length-scaled estimate instead of a flat delay.
_PLAYBACK_CHARS_PER_SEC: float = 14.0
_PLAYBACK_PAD_SECS: float = 1.5
_PLAYBACK_MIN_SECS: float = 2.0
# Ceiling on degraded-path waits.  High enough that any realistic configured
# announcement (a few sentences) is never undercut by the clamp — at 14 chars/s
# this covers ~600 characters of speech.  It exists only to bound the wait if
# an absurdly long text is configured, not to trim normal announcements.
_PLAYBACK_MAX_SECS: float = 45.0


def estimate_playback_secs(text: str | None) -> float:
    """Estimate how many seconds ``text`` takes to speak over the phone.

    Conservative (slightly over-estimates) so degraded fallback paths wait
    long enough for the announcement to finish rather than clipping it.
    Returns the minimum estimate when ``text`` is empty/unknown.
    """
    if not text:
        return _PLAYBACK_MIN_SECS
    est = len(text) / _PLAYBACK_CHARS_PER_SEC + _PLAYBACK_PAD_SECS
    return max(_PLAYBACK_MIN_SECS, min(_PLAYBACK_MAX_SECS, est))


class FunctionMapper:
    """Maps database tool configurations to executable Pipecat functions.

    Usage:
        # At voice agent initialization
        tools = db.query(Tool).filter(Tool.is_active == "true").all()
        mapper = FunctionMapper(
            call_sid="CA1234...",
            stream_sid="MZ1234...",
            from_number="+15551234567",
            to_number="+15559876543",
            twilio_account_sid="AC...",  # Hotel's sub-account
            twilio_auth_token="xxx",      # Hotel's sub-account token
        )

        # Register all tools with LLM
        for tool in tools:
            function_schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(function_schema['name'], handler)
    """

    def __init__(
        self,
        call_sid: str = None,
        stream_sid: str = None,
        from_number: str = None,
        to_number: str = None,
        twilio_account_sid: str = None,
        twilio_auth_token: str = None,
        call_handler: "CallHandler" = None,
        db_session=None,
        account_id: str = None,
        account_name: str = None,
        escalation_target: str = None,
        property_id: str = None,
        session_factory=None,
        assistant_timezone: str = "UTC",
    ):
        """Initialize function mapper with call context and Twilio credentials.

        Args:
            call_sid: Twilio call SID (required for call transfers)
            stream_sid: Twilio stream SID (for stopping the media stream)
            from_number: Original caller's phone number (for callerId on transfer)
            to_number: The hotel's phone number that was called
            twilio_account_sid: Hotel's Twilio sub-account SID
            twilio_auth_token: Hotel's Twilio sub-account auth token
            call_handler: Reference to CallHandler for transcript saving
            db_session: SQLAlchemy database session for integration API calls
            account_id: Account ID for multi-tenant integration access
            account_name: Human-readable account name for SMS template interpolation
        """
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self.from_number = from_number
        self.to_number = to_number
        self.call_handler = call_handler
        self.db_session = db_session
        # session_factory: callable → Session.  Set to SessionLocal on live voice
        # calls (where db_session=None because the setup session is closed before
        # the call starts).  Threaded into FlowExecutor and used by
        # _map_dynamic_operation so each DB operation opens its own short-lived
        # session and closes it immediately — identical to the SAVE_RECORD pattern.
        self.session_factory = session_factory
        self.account_id = account_id
        self.account_name = account_name or ""
        # Assistant-level "talk to a human" number. Powers both the always-on
        # request_human tool and the maxRetries escalation fallback inside
        # FlowExecutor. None → escalation disabled (fail closed).
        self.escalation_target = escalation_target
        # Per-property isolation (Task #327). Resolved once at contact start from
        # the dialed number / assistant and threaded into every FlowExecutor and
        # ActionContext so integration resolution is scoped to (account, property).
        # None → legacy account-only scoping.
        self.property_id = property_id
        self.assistant_timezone = assistant_timezone or "UTC"

        # Store flow executors by tool name for state persistence across turns
        self._flow_executors: Dict[str, FlowExecutor] = {}
        self._flow_context = CallFlowContext()

        # Store non-flow tool schemas for inclusion in dynamic tool updates
        # These tools should always remain available even during flow execution
        self._non_flow_tool_schemas: List[Dict[str, Any]] = []

        # Names of non-flow schemas that map to END_CALL tools.  Populated by
        # call_handler when registering end_call tools.  Used by
        # update_llm_tools_for_flow to block the global end_call when the flow
        # is sitting on a required action node (e.g. save_record) — preventing
        # the LLM from skipping the action by calling end_call directly.
        self._end_call_schema_names: set = set()

        # TTS completion watcher — set by CallHandler after pipeline creation.
        # Used by transfer handlers to await real TTS completion instead of a
        # fixed sleep, ensuring the pre-transfer message is never clipped.
        self._tts_completion_watcher = None

        # TTS service instance — set by CallHandler after pipeline creation.
        # Used by transfer handlers to check audio context state after interruptions
        # and create a fresh context when needed before pushing TTSSpeakFrame.
        self._tts_service = None

        # Twilio mark watcher — set by CallHandler after pipeline creation.
        # Used to wait until Twilio confirms the caller heard transfer audio.
        self._twilio_mark_watcher = None

        # Stores the spoken pre-transfer message so _execute_transfer can append
        # it to the saved transcript.  TTSSpeakFrame bypasses the LLM context, so
        # the message would otherwise be invisible to the ACW LLM.
        self._pending_pre_transfer_message: Optional[str] = None

        # CallEventQueue — injected by CallHandler after pipeline initialization.
        # Used to log pipeline events non-blockingly.
        self._event_queue = None

        # Track whether user_first_speech has been logged yet
        self._first_speech_logged = False

        # Twilio client for call transfers - use hotel's sub-account credentials
        self.twilio_client = None
        self.twilio_account_sid = twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN")

        if self.twilio_account_sid and self.twilio_auth_token:
            self.twilio_client = TwilioClient(self.twilio_account_sid, self.twilio_auth_token)
            logger.info(
                f"✅ Twilio client initialized for call {call_sid} (Account: {self.twilio_account_sid[:10]}...)"
            )

    def set_tts_completion_watcher(self, watcher) -> None:
        """Attach the TtsCompletionWatcher created by the voice pipeline.

        Called by CallHandler immediately after pipeline creation so that
        transfer handlers can use wait_for_bot_done() instead of fixed sleeps.

        Args:
            watcher: TtsCompletionWatcher instance from VoiceEngineFactory.create_pipeline()
        """
        self._tts_completion_watcher = watcher
        logger.debug(f"TtsCompletionWatcher linked to FunctionMapper for call {self.call_sid}")

    def set_tts_service(self, tts_service) -> None:
        """Attach the TTS service instance created by the voice pipeline.

        Called by CallHandler immediately after pipeline creation so that
        transfer handlers can check audio context state after interruptions and
        create a fresh context when needed before pushing a TTSSpeakFrame.

        Args:
            tts_service: TTSService instance from VoiceEngineFactory.create_pipeline()
        """
        self._tts_service = tts_service
        logger.debug(f"TTS service linked to FunctionMapper for call {self.call_sid}")

    def set_twilio_mark_watcher(self, watcher) -> None:
        """Attach the TwilioMarkWatcher created by the voice pipeline."""
        self._twilio_mark_watcher = watcher
        logger.debug(f"TwilioMarkWatcher linked to FunctionMapper for call {self.call_sid}")

    async def _await_twilio_playback_mark(
        self, label: str, expected_speech_text: str | None = None
    ) -> bool:
        """Wait for Twilio to acknowledge playback up to this point.

        Degraded paths (no mark watcher, or mark ack timed out / never arrived)
        do NOT proceed immediately: audio confirmed written to the WebSocket may
        still be sitting unplayed in Twilio's outbound buffer, so we wait a
        conservative length-scaled estimate of the announcement's remaining
        playback time before returning.  A received mark ack skips the wait.
        """
        if self._twilio_mark_watcher is None:
            _est = estimate_playback_secs(expected_speech_text)
            logger.warning(
                f"⏳ Playback-mark DEGRADED path (no TwilioMarkWatcher) for call "
                f"{self.call_sid} ({label}) — waiting {_est:.1f}s playback estimate "
                f"instead of mark acknowledgement"
            )
            await asyncio.sleep(_est)
            return False

        mark_name = f"{label}:{self.call_sid}:{uuid.uuid4().hex[:8]}"
        _reason = None
        acked = False
        try:
            acked = await self._twilio_mark_watcher.send_mark_and_wait(
                mark_name, timeout=TWILIO_MARK_TIMEOUT_SECS
            )
            if not acked:
                _reason = f"ack timeout/missing after {TWILIO_MARK_TIMEOUT_SECS}s"
        except Exception as _mark_err:
            # A failed mark SEND is just as unconfirmed as a missing ack — the
            # announcement may still be playing.  Treat it as degraded, never
            # as permission to proceed immediately.
            _reason = f"mark send/wait raised: {_mark_err}"
        if _reason is not None:
            _est = estimate_playback_secs(expected_speech_text)
            logger.warning(
                f"⏳ Playback-mark DEGRADED path ({_reason}) for call "
                f"{self.call_sid} ({label}) — waiting additional {_est:.1f}s "
                f"playback estimate before proceeding"
            )
            await asyncio.sleep(_est)
        return acked

    async def _rest_hangup(self, label: str) -> None:
        """Issue a Twilio REST hangup (status=completed) for reliable PSTN teardown.

        With auto_hang_up=False on TwilioFrameSerializer, pushing EndFrame only
        closes the WebSocket — Twilio may not hang up the PSTN leg immediately.
        Skipped in the simulator (no twilio_client / call_sid) and handled
        gracefully on 404 (call already ended).
        """
        if not (self.twilio_client and self.call_sid):
            logger.debug(
                f"No Twilio client/call_sid — skipping REST hangup ({label}; simulator or test context)"
            )
            return
        try:
            await asyncio.to_thread(
                lambda: self.twilio_client.calls(self.call_sid).update(status="completed")
            )
            logger.info(f"📵 REST hangup issued for call {self.call_sid} ({label})")
        except _TwilioRestException as _e:
            if _e.status == 404:
                logger.warning(
                    f"REST hangup 404 for call {self.call_sid} ({label}) — call already ended"
                )
            else:
                logger.warning(
                    f"REST hangup failed for call {self.call_sid} ({label}): {_e} — continuing EndFrame"
                )
        except Exception as _e:
            logger.warning(
                f"REST hangup unexpected error for call {self.call_sid} ({label}): {_e} — continuing EndFrame"
            )

    async def _finalize_call_end(
        self, llm, label: str, speech_text: str | None = None
    ) -> None:
        """Hang up the call AFTER the goodbye has been fully heard.

        Runs as a post-speech callback (via TtsCompletionWatcher), so it starts
        only after BotStoppedSpeakingFrame. It then awaits a Twilio playback
        mark — Twilio acknowledges the mark only after all buffered outbound
        audio has actually played to the caller — before issuing the REST
        hangup and ending the pipeline. Same caller-heard boundary transfers use.
        """
        try:
            await self._await_twilio_playback_mark(label, expected_speech_text=speech_text)
        except Exception as _mark_err:
            logger.warning(
                f"Playback-mark wait failed for call {self.call_sid} ({label}): {_mark_err} — proceeding with hangup"
            )
        await self._rest_hangup(label)
        await llm.push_frame(EndFrame())

    def _run_after_speech(
        self,
        callback,
        label: str,
        reset: bool = True,
        context_id: str | None = None,
        speech_text: str | None = None,
    ) -> None:
        """Register ``callback`` to fire once the current speech utterance completes.

        Binding strategy (in priority order):

        1. **Two-stage chain (context-ID + BotStopped)** — if ``context_id`` is
           provided, or if ``reset=False`` and the TTS service exposes
           ``_turn_context_id``, a wrapper is registered on the TTS service's
           per-context registry.  When ``on_audio_context_completed`` fires (TTS
           has pushed all audio frames downstream), the wrapper resets
           ``TtsCompletionWatcher`` and schedules the real callback on it.  The
           callback then fires only when ``BotStoppedSpeakingFrame`` arrives
           upstream from ``transport.output()`` — i.e. after audio bytes are
           confirmed written to the Twilio WebSocket.

           Why two stages?  ``on_audio_context_completed`` fires at the TTS
           service layer, not at the transport layer.  Audio frames still have
           4-5 pipeline hops to travel before reaching ``transport.output()``.
           If the mark were sent at context-ID completion time, it would race
           past those in-flight audio frames in the pipeline queues, arrive at
           Twilio before the audio, and be ack'd before the caller hears anything.
           ``BotStoppedSpeakingFrame`` fires from the transport's audio task
           *after* all audio bytes are written to the WebSocket — that is the
           correct "safe to send mark and hang up" signal.

           Interruption safety is preserved: if the context is interrupted,
           ``on_audio_context_interrupted`` discards the wrapper before it runs,
           so no stale hangup fires.

        2. **BotStoppedSpeakingFrame watcher** — fallback when context-ID
           binding is unavailable (unrecognised TTS provider).  ``reset=True``
           clears the watcher before registering so it waits for the next
           ``TTSSpeakFrame`` the caller is about to push.

        3. **Length-scaled delay** — last resort when neither watcher nor TTS
           service is available (simulator / test context).  Waits
           max(3 s, estimate_playback_secs(speech_text)) so long announcements
           are not clipped by a flat delay.

        Args:
            callback:    Async callable with no arguments.
            label:       Human-readable label for log messages.
            reset:       For fallback path only — clears watcher before
                         registering.  For context-ID path, this has no effect.
            context_id:  Specific audio context_id to bind to.  When None and
                         reset=False, the method reads _turn_context_id from the
                         TTS service (the LLM's current utterance context).
        """
        # ── 1. Two-stage chain: context-ID → BotStoppedSpeakingFrame ──────────
        effective_ctx_id = context_id
        if (
            effective_ctx_id is None
            and not reset
            and self._tts_service is not None
        ):
            # For flow handlers: the LLM spoke the terminal message; its active
            # context is the one whose completion we want to wait for.
            effective_ctx_id = getattr(self._tts_service, "_turn_context_id", None)

        if (
            effective_ctx_id is not None
            and self._tts_service is not None
            and hasattr(self._tts_service, "register_context_done_callback")
        ):
            # Capture the watcher at registration time so the closure is
            # independent of any later assignment to self._tts_completion_watcher.
            _watcher = self._tts_completion_watcher

            async def _ctx_done_wrapper(_cb=callback, _w=_watcher):
                # Stage 1 complete: on_audio_context_completed has fired.
                # TTS has finished pushing audio frames downstream, but they
                # have NOT yet reached transport.output() or the Twilio WebSocket.
                # Hand off to TtsCompletionWatcher so the terminal action fires
                # only after BotStoppedSpeakingFrame arrives from the transport
                # (audio confirmed written to the WebSocket, in Twilio's buffer).
                if _w is not None:
                    _w.reset()
                    _w.schedule_after_speech(_cb, label=label)
                else:
                    # No watcher available — DEGRADED path.  Context completion
                    # only means TTS pushed all audio frames downstream; they
                    # have NOT yet reached the transport/Twilio (see the race
                    # rationale above).  Running the terminal action now could
                    # clip the announcement, so wait a length-scaled playback
                    # estimate first — the same caller-heard bound the other
                    # degraded paths use.
                    _delay = max(3.0, estimate_playback_secs(speech_text))
                    logger.warning(
                        f"⏳ {label}: context completed but no TtsCompletionWatcher "
                        f"for call {self.call_sid} — DEGRADED path: waiting "
                        f"{_delay:.1f}s playback estimate before terminal action"
                    )
                    await asyncio.sleep(_delay)
                    await _cb()

            self._tts_service.register_context_done_callback(effective_ctx_id, _ctx_done_wrapper)
            logger.info(
                f"📋 {label} callback bound to audio context {effective_ctx_id[:8]}... "
                f"(→ BotStopped chain) for call {self.call_sid}"
            )
            return

        # ── 2. BotStoppedSpeakingFrame watcher (fallback) ─────────────────────
        if self._tts_completion_watcher is not None:
            if reset:
                self._tts_completion_watcher.reset()
            self._tts_completion_watcher.schedule_after_speech(callback, label=label)
            logger.info(
                f"📋 {label} callback registered (BotStopped fallback) "
                f"for call {self.call_sid}"
            )
            return

        # ── 3. Length-scaled delay (last resort) ──────────────────────────────
        # No watcher exists, so we cannot observe playback at all.  Wait long
        # enough for the announcement to be synthesized AND played: a flat 3 s
        # clipped longer announcements.  estimate_playback_secs is conservative
        # and clamped, and we never wait less than the old 3 s floor.
        _delay = max(3.0, estimate_playback_secs(speech_text))

        async def _delayed():
            await asyncio.sleep(_delay)
            await callback()

        asyncio.create_task(_delayed())
        logger.warning(
            f"⏳ No TtsCompletionWatcher for call {self.call_sid} — DEGRADED path: "
            f"using {_delay:.1f}s length-scaled fallback delay for {label} "
            f"(speech_text={'unknown' if speech_text is None else f'{len(speech_text)} chars'})"
        )

    def set_event_queue(self, event_queue) -> None:
        """Attach the CallEventQueue for this call.

        Called by CallHandler after pipeline creation so pipeline events
        (user_first_speech, transfer_initiated) can be logged non-blockingly.

        Args:
            event_queue: CallEventQueue instance
        """
        self._event_queue = event_queue
        logger.debug(f"CallEventQueue linked to FunctionMapper for call {self.call_sid}")

    def log_event(
        self,
        event_type: str,
        event_source: str = "pipecat",
        severity: str = "info",
        details: dict = None,
    ) -> None:
        """Log a pipeline event via the event queue (non-blocking)."""
        if getattr(self, "_event_queue", None) is not None:
            self._event_queue.log(
                event_type, event_source=event_source, severity=severity, details=details
            )

    async def wait_for_bot_done(self, timeout: float = 15.0) -> None:
        """Wait until the bot has finished speaking.

        Legacy/fallback method — kept for edge cases.  Transfer handlers should
        use TtsCompletionWatcher.schedule_after_speech() instead so the Twilio
        REST call happens outside Pipecat's 10-second function-call timeout.

        This method is a pure waiter — it does NOT reset the watcher.
        Callers that push a new TTSSpeakFrame must call
        ``self._tts_completion_watcher.reset()`` *before* the push so the
        watcher captures the correct BotStoppedSpeakingFrame.  Callers that
        only want to ensure the bot is already idle should call this without
        resetting so that an already-set event returns immediately.

        Falls back to a short fixed delay when the watcher is unavailable.

        Args:
            timeout: Maximum seconds to wait (default 15).  Transfer proceeds
                     regardless once the timeout expires.
        """
        import asyncio

        if self._tts_completion_watcher is not None:
            logger.info(f"⏳ Awaiting TTS completion before transfer for call {self.call_sid}")
            completed = await self._tts_completion_watcher.wait_until_done(timeout=timeout)
            if completed:
                logger.info(f"✅ TTS completion confirmed for call {self.call_sid}")
            else:
                logger.warning(
                    f"⚠️ TTS completion timed out after {timeout}s for call {self.call_sid} "
                    "— proceeding with transfer anyway"
                )
        else:
            # Fallback: watcher not available (no tools registered for this call)
            logger.warning(
                f"No TtsCompletionWatcher available for call {self.call_sid} — "
                "using 3 s fallback delay before transfer"
            )
            await asyncio.sleep(3.0)

    def track_tool_usage(
        self, tool_name: str, is_flow: bool = False, flow_id: Optional[str] = None
    ):
        """Record tool usage in call log.

        Args:
            tool_name: Name of the tool or flow.
            is_flow: True when this is a flow tool (not a standalone tool).
            flow_id: UUID string of the flow tool; persisted to call_logs.flow_id
                     so each call log links to the exact flow that ran it.
        """
        if not self.call_sid:
            return
        try:
            from ..database import SessionLocal
            from ..services.call_logger import CallLogger

            db = SessionLocal()
            try:
                call_logger = CallLogger(db)
                call_logger.record_tool_usage(
                    call_sid=self.call_sid,
                    tool_name=tool_name,
                    is_flow=is_flow,
                    flow_id=flow_id,
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to track tool usage: {e}")

    def register_non_flow_tool_schema(self, schema_dict: Dict[str, Any]):
        """Register a non-flow tool schema for inclusion in dynamic tool updates.

        These tools remain available during flow execution.
        """
        self._non_flow_tool_schemas.append(schema_dict)

    def _capture_direct_speech(self, text: str) -> None:
        """Anchor text spoken via a direct ``TTSSpeakFrame`` push with a real
        elapsed-time capture, so ``_extract_transcript`` can place it in its
        true chronological position instead of guessing by array position.

        Flow collection prompts, API ``thinkingMessage``, API completion
        bridges (``onComplete``/``onError``), and direct flow responses all
        bypass the LLM completion cycle by pushing ``TTSSpeakFrame`` straight
        into the pipeline. ``context_aggregator.assistant()`` sits at the very
        end of the pipeline (after TTS) and only flushes its buffered text
        once the *next* real LLM completion is committed — so this text can
        land in the raw context array merged with, or behind, a message that
        was actually generated after the caller's next reply. Without a real
        timestamp here, ``_extract_transcript``'s interpolation has no way to
        know that and can order the question after its own answer (Task
        #598). Recording it here mirrors ``on_llm_response`` exactly, so the
        same prefix-matched annotation + global chronological sort that
        already fixes up genuine LLM turns also fixes up these direct pushes.

        Guarded with getattr so tests that construct FunctionMapper via
        __new__ without setting call_handler/call_sid don't crash, and so the
        simulator (no call_handler, no TTS) is unaffected.
        """
        _ch = getattr(self, "call_handler", None)
        _cs = getattr(self, "call_sid", None)
        if not (_ch and _cs) or not text:
            return
        _resp_list = getattr(_ch, "pending_responses", {}).get(_cs)
        if _resp_list is None:
            return
        from datetime import datetime as _dt

        _start = getattr(_ch, "call_start_times", {}).get(_cs)
        _now = _dt.utcnow()
        _resp_list.append(
            {
                "text": text,
                "elapsed_s": (_now - _start).total_seconds() if _start else 0.0,
            }
        )

    def _record_action_timestamp(self, function_name: str) -> None:
        """Append an elapsed-time entry for a tool invocation to action_timestamps.

        Called from the universal handler wrapper applied at registration time in
        call_handler so that EVERY registered tool (flow trigger, flow function,
        non-flow custom, escalation) is covered without duplicating logic.
        Guarded with getattr so tests that construct FunctionMapper via __new__
        without setting call_handler/call_sid don't crash.
        """
        _ch = getattr(self, "call_handler", None)
        _cs = getattr(self, "call_sid", None)
        if not (_ch and _cs):
            return
        _ts_list = getattr(_ch, "action_timestamps", {}).get(_cs)
        if _ts_list is None:
            return
        from datetime import datetime as _dt

        _start = getattr(_ch, "call_start_times", {}).get(_cs)
        _now = _dt.utcnow()
        _ts_list.append(
            {
                "name": function_name,
                "elapsed_s": (_now - _start).total_seconds() if _start else 0.0,
            }
        )

    def wrap_with_timestamp(self, function_name: str, handler: Callable) -> Callable:
        """Return a wrapper around *handler* that records an action timestamp.

        Applied at every function_handlers registration point in call_handler so
        that every tool type (flow trigger, flow function, non-flow custom/MCP,
        escalation) records its invocation time under its canonical function name.
        _extract_transcript then looks up timestamps by name, not position, so
        mixed-tool transcripts are ordered correctly.
        """

        async def _timestamped(params):
            self._record_action_timestamp(function_name)
            return await handler(params)

        return _timestamped

    def get_flow_executors(self) -> list:
        """Return the FlowExecutors created for this call's flow tools.

        Used by call_handler to inject each flow's static system-prompt
        additions into the live LLM system prompt before the pipeline is built.
        Empty when the assistant has no flow tools (or only empty flows).
        """
        return list(self._flow_executors.values())

    def get_flow_llm_override(self) -> dict | None:
        """Return the first non-empty per-flow LLM override found across all flow tools.

        Task #477 — flow tools can configure their own LLM provider, model,
        temperature, and max_tokens. The first tool with any non-None value wins
        (typical deployments have a single flow tool per assistant). Returns None
        when no executor has an override set (i.e. all values are None).
        """
        for executor in self._flow_executors.values():
            override = getattr(executor, "_llm_override", {}) or {}
            if any(v is not None for v in override.values()):
                return override
        return None

    @staticmethod
    def _flow_has_started(executor: FlowExecutor) -> bool:
        """Return whether a flow may no longer accept its start trigger."""
        state = executor.state
        return bool(
            state.is_complete
            or state.graph_exhausted
            or (
                state.current_node_id is not None
                and state.current_node_id != executor.flow_config.initial_node
            )
        )

    def update_llm_tools_for_flow(self, tool_name: str):
        """Update the LLM context tools to only expose the current/next slot function.

        This is called after each slot collection to enforce strict flow order.
        The LLM will only see the function for the current slot, preventing it
        from calling functions for slots that should be collected later.

        Non-flow tools (transfer, end call, etc.) and knowledge base remain available.
        """
        if not self.call_handler or not self.call_sid:
            logger.warning("Cannot update LLM tools: missing call_handler or call_sid")
            return

        llm_context = self.call_handler.call_contexts.get(self.call_sid)
        if not llm_context:
            logger.warning(f"Cannot update LLM tools: no context for call {self.call_sid}")
            return

        executor = self._flow_executors.get(tool_name)
        if not executor:
            logger.warning(f"Cannot update LLM tools: no executor for flow {tool_name}")
            return

        try:
            flow_schemas = executor.get_function_schemas()

            # Block the global end_call from the tool list while any required
            # side-effect (SAVE_RECORD, API_REQUEST, CAPABILITY, CONFIRMATION,
            # SET_VARIABLE) has not yet fired — either because the flow is sitting
            # directly on such a node, OR because the current node (typically a
            # collect node) has a side-effect node pending downstream.
            #
            # The second case is the root cause of the "decline loses the record"
            # bug: while on the final "anything else?" collect node, SAVE_RECORD
            # is downstream but is_on_required_action_node() returned False (collect
            # nodes are not action nodes), leaving end_call available for the LLM to
            # skip straight past SAVE_RECORD on a "No" answer.
            #
            # Transfer/escalation tools are intentionally NOT blocked — callers
            # can always escalate to a human even mid-flow.  The flow's own
            # end_call_<node_id> is still exposed via get_function_schemas() above.
            on_required_action = (
                executor.is_on_required_action_node()
                or executor.has_pending_side_effect_downstream()
            )

            function_schema_objects = []

            # 1. Include non-flow tools (transfer, end call, etc.)
            # Note: query_hotel_knowledge is intentionally omitted — the knowledge
            # base is injected directly into the system prompt, and the function
            # handler is no longer registered.  Exposing an unregistered function
            # here would cause LLM call errors if the model tried to invoke it.
            for non_flow_schema in self._non_flow_tool_schemas:
                # Block global end_call while a required action node hasn't fired yet.
                # Transfer/escalation tools are intentionally NOT blocked — callers
                # can always escalate to a human even mid-flow.
                if on_required_action and non_flow_schema["name"] in self._end_call_schema_names:
                    continue
                func_schema = FunctionSchema(
                    name=non_flow_schema["name"],
                    description=non_flow_schema.get("description", ""),
                    properties=non_flow_schema.get("parameters", {}).get("properties", {}),
                    required=non_flow_schema.get("parameters", {}).get("required", []),
                )
                function_schema_objects.append(func_schema)

            # 2. Only an unstarted flow may be started. Keeping this trigger
            # after the flow entered its first graph node lets an LLM retry
            # replay the greeting and overwrite in-progress caller facts.
            if not self._flow_has_started(executor):
                trigger_schema = FunctionSchema(
                    name=f"start_{sanitize_function_name(tool_name)}",
                    description=(
                        f"Start the {tool_name} conversation flow. Call this IMMEDIATELY, in the "
                        "same turn the customer expresses that intent — do NOT ask the customer any "
                        "questions first. All parameters are optional: pass only details the customer "
                        "has already volunteered; the flow itself collects everything else in order."
                    ),
                    properties={
                        var.key: executor._create_slot_function(var)["function"]["parameters"][
                            "properties"
                        ][var.key]
                        for var in executor.flow_config.variables
                    },
                    required=[],
                )
                function_schema_objects.append(trigger_schema)

            # 3. Include current flow functions (only current slot due to get_function_schemas logic)
            for schema in flow_schemas:
                func_def = schema.get("function", schema)
                func_schema = FunctionSchema(
                    name=func_def["name"],
                    description=func_def.get("description", ""),
                    properties=func_def.get("parameters", {}).get("properties", {}),
                    required=func_def.get("parameters", {}).get("required", []),
                )
                function_schema_objects.append(func_schema)

            new_tools = ToolsSchema(standard_tools=function_schema_objects)
            llm_context.set_tools(new_tools)

            func_names = [f.name for f in function_schema_objects]
            logger.info(f"🔄 Updated LLM tools for flow {tool_name}: {func_names}")

        except Exception as e:
            logger.error(f"Failed to update LLM tools for flow {tool_name}: {e}")

    def map_tool_to_function(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Convert a database tool to a Pipecat function schema and handler.

        Args:
            tool: Database tool model

        Returns:
            Tuple of (function_schema, handler_function)

        Example:
            schema, handler = mapper.map_tool_to_function(transfer_tool)
            # schema = {"name": "transfer_to_front_desk", "description": "...", "parameters": {...}}
            # handler = async function that actually performs the transfer
        """
        safe_name = sanitize_function_name(tool.name)
        if safe_name != tool.name:
            logger.warning(
                f"Tool '{tool.name}' (id={getattr(tool, 'id', '?')}) has a name that requires "
                f"sanitization for the OpenAI API. It will be sent as '{safe_name}'. "
                "Consider renaming the tool to use only letters, digits, spaces, hyphens, "
                "and underscores to suppress this warning."
            )

        if tool.tool_type == ToolType.TRANSFER_CALL:
            return self._map_transfer_call(tool)
        elif tool.tool_type == ToolType.API_REQUEST:
            return self._map_api_request(tool)
        elif tool.tool_type == ToolType.END_CALL:
            return self._map_end_call(tool)
        elif tool.tool_type == ToolType.SEND_SMS:
            return self._map_send_sms(tool)
        elif tool.tool_type == ToolType.SEND_EMAIL:
            return self._map_send_email(tool)
        elif tool.tool_type == ToolType.FLOW:
            return self._map_flow(tool)
        elif tool.tool_type == ToolType.CAPABILITY:
            return self._map_capability(tool)
        elif tool.tool_type == ToolType.DYNAMIC_OPERATION:
            return self._map_dynamic_operation(tool)
        else:
            raise ValueError(f"Unknown tool type: {tool.tool_type}")

    def build_escalation_tool(self) -> Optional[tuple[Dict[str, Any], Callable]]:
        """Build the always-on ``request_human`` tool from the assistant-level
        escalation number.

        Returns ``None`` when no escalation number is configured — fail-closed,
        so the tool is simply never offered and the LLM can never attempt a
        transfer to a number that does not exist. When configured, it reuses the
        exact same Twilio transfer machinery as a normal Transfer Call tool by
        mapping a transient, in-memory transfer ``Tool`` (never persisted).
        """
        if not self.escalation_target:
            return None

        escalation_tool = Tool(
            name="request_human",
            tool_type=ToolType.TRANSFER_CALL,
            description=(
                "Connect the caller to a human agent. Call this ONLY when the "
                "caller explicitly asks to speak with a person, human, agent, "
                "representative, or a live staff member — or clearly no longer "
                "wants to talk to the automated assistant. Do not call it for "
                "ordinary questions you can answer yourself."
            ),
            config={
                "phone_number": self.escalation_target,
                "transfer_mode": "warm",
                "pre_transfer_message": (
                    "Sure — let me connect you with someone who can help. "
                    "One moment please."
                ),
            },
        )
        return self._map_transfer_call(escalation_tool)

    def _map_transfer_call(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map transfer call tool to Pipecat function.

        Function schema tells LLM:
        - When to call this function (description)
        - What parameters it needs (usually none for simple transfer)

        Handler function:
        - Says pre-transfer message
        - Transfers call to configured number
        - Ends bot's session
        """
        stored_phone = tool.config.get("phone_number") or ""
        country_code = tool.config.get("country_code") or ""
        raw_extension = tool.config.get("extension") or ""
        # Normalise extension to digits-only for safe TwiML/SIP interpolation.
        import re as _re_ext

        extension_digits = _re_ext.sub(r"[^\d]", "", raw_extension)
        extension = extension_digits if extension_digits else None
        # Configurable pause before DTMF extension digits. TwiML sendDigits uses
        # 'w' for a 0.5-second pause (NOT comma, which is silently ignored).
        extension_pause_seconds = float(tool.config.get("extension_pause_seconds") or 1.0)
        extension_pause_commas = "w" * max(1, round(extension_pause_seconds / 0.5))
        # Build E.164 dial target. New records store country_code + local digits
        # separately; legacy records stored the full E.164 in phone_number.
        if country_code and not stored_phone.startswith("+"):
            phone_number = f"{country_code}{stored_phone}"
        else:
            phone_number = stored_phone
        pre_message = tool.config.get("pre_transfer_message", "One moment please...")
        transfer_mode = tool.config.get("transfer_mode", "warm")

        # OpenAI function schema
        function_schema = {
            "name": sanitize_function_name(tool.name),
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {},  # No parameters needed for simple transfer
                "required": [],
            },
        }

        # Handler function using Pipecat's FunctionCallParams pattern
        async def transfer_handler(params: FunctionCallParams):
            """Handler called when LLM decides to transfer call.

            Transfer Flow (decoupled from Pipecat function-call timeout):
                1. AI says pre-transfer message via Pipecat TTS (assistant's configured voice).
                2. Register _execute_transfer as a one-shot callback on TtsCompletionWatcher,
                   then return immediately to Pipecat — well within the 10s timeout.
                3. When BotStoppedSpeakingFrame arrives (speech done), the watcher fires
                   _execute_transfer as an asyncio task, outside Pipecat's timeout window.
                4. _execute_transfer: saves transcript, builds TwiML, calls Twilio REST API.
                5. Pipeline ends when Twilio closes the WebSocket after receiving the update.

            Fallback (no watcher): schedules _execute_transfer after a 3s fixed delay.
            """
            import asyncio as _asyncio
            import re as _re

            # Track tool usage
            self.track_tool_usage(tool.name)

            # Log transfer_initiated event (non-blocking)
            self.log_event(
                "transfer_initiated",
                event_source="app",
                severity="info",
                details={
                    "tool": tool.name,
                    "transfer_to": phone_number,
                    "transfer_mode": transfer_mode,
                },
            )

            async def _execute_transfer():
                """Performs the actual Twilio transfer — runs as an asyncio task after
                TTS finishes, completely outside Pipecat's function-call timeout.

                Pushes EndFrame only after a confirmed successful Twilio update
                (2xx response from calls().update()).  On 404 / any transfer error
                EndFrame is NOT pushed so the pipeline remains active — the AI can
                continue the conversation or Twilio's natural WebSocket close will
                end the pipeline when the call actually terminates.

                With auto_hang_up=False (TwilioFrameSerializer), EndFrame closes
                the WebSocket without issuing a Twilio REST hangup, so Twilio
                continues executing the TwiML it received (warm <Dial> or cold REFER).
                """
                _transfer_succeeded = False
                _call_already_ended = False
                try:
                    if self.twilio_client and self.call_sid:
                        try:
                            # Capture recording SID before launching parallel tasks.
                            _rec_sid = (
                                self.call_handler.call_recording_sids.get(self.call_sid)
                                if self.call_handler
                                else None
                            )

                            # Stop recording and save transcript concurrently — they are
                            # independent of each other.  Both must finish before the Twilio
                            # REST call so the recording is stopped and the transcript is
                            # persisted before the WebSocket closes.
                            #
                            # Recording stop: blocking Twilio SDK call, run in a thread.
                            #   Failures are warned only — never blocks the transfer.
                            # Transcript save: async DB write.
                            #   The pre-transfer message (spoken via TTSSpeakFrame, which
                            #   bypasses LLM context) is injected manually here.

                            async def _stop_recording_task():
                                if _rec_sid:
                                    try:
                                        await _asyncio.to_thread(
                                            lambda: (
                                                self.twilio_client.calls(self.call_sid)
                                                .recordings(_rec_sid)
                                                .update(status="stopped")
                                            )
                                        )
                                        logger.info(
                                            f"🛑 Recording {_rec_sid} stopped before transfer for call {self.call_sid}"
                                        )
                                        self.call_handler.call_recording_sids.pop(
                                            self.call_sid, None
                                        )
                                    except Exception as _stop_err:
                                        logger.warning(
                                            f"Failed to stop recording before transfer for call {self.call_sid}: {_stop_err}"
                                        )

                            async def _save_transcript_task():
                                if self.call_handler and hasattr(
                                    self.call_handler, "_save_call_transcript"
                                ):
                                    try:
                                        llm_context = self.call_handler.call_contexts.get(
                                            self.call_sid
                                        )
                                        extra = []
                                        if self._pending_pre_transfer_message:
                                            _pt_entry = {
                                                "role": "assistant",
                                                "content": self._pending_pre_transfer_message,
                                                "interrupted": False,
                                            }
                                            # Anchor it in the chronological sort
                                            # (Task #534) instead of relying purely
                                            # on tail-interpolation — it bypassed
                                            # the LLM context, so it has no other
                                            # captured timestamp of its own.
                                            from datetime import datetime as _dt_pt

                                            _start = getattr(
                                                self.call_handler, "call_start_times", {}
                                            ).get(self.call_sid)
                                            if _start:
                                                _pt_entry["_elapsed_s"] = (
                                                    _dt_pt.utcnow() - _start
                                                ).total_seconds()
                                            extra.append(_pt_entry)
                                            self._pending_pre_transfer_message = None
                                        await self.call_handler._save_call_transcript(
                                            self.call_sid,
                                            llm_context,
                                            extra_messages=extra if extra else None,
                                            skip_billing=True,
                                        )
                                        logger.info(
                                            f"📝 Saved transcript before transfer for call {self.call_sid}"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"Error saving transcript before transfer: {e}"
                                        )

                            _mark_task = _asyncio.create_task(
                                self._await_twilio_playback_mark(
                                    "transfer", expected_speech_text=pre_message
                                )
                            )
                            _gather_t0 = _asyncio.get_event_loop().time()
                            await _asyncio.gather(
                                _mark_task,
                                _stop_recording_task(),
                                _save_transcript_task(),
                            )
                            _pre_transfer_ms = int(
                                (_asyncio.get_event_loop().time() - _gather_t0) * 1000
                            )
                            logger.info(
                                f"⏱️ Pre-transfer tasks completed in {_pre_transfer_ms}ms "
                                f"(playback mark + recording stop + transcript save, parallel) "
                                f"for call {self.call_sid}"
                            )

                            # Stop the idle timer now that the AI leg is ending.
                            # Prevents ghost idle_timeout events during the transfer
                            # ringing/bridging window (the 30 s countdown from the last
                            # user utterance fires AFTER the transfer if not cancelled here).
                            if self.call_handler is not None:
                                self.call_handler.cancel_idle_tracker(self.call_sid)

                            # Build mode-specific TwiML. Do not include an
                            # explicit stream-stop verb: this call uses
                            # bidirectional Connect/Stream, and Twilio stops
                            # that stream when the live call is updated or the
                            # WebSocket closes.
                            twiml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]

                            if transfer_mode == "cold":
                                # Cold Transfer (SIP REFER)
                                # Twilio sends a SIP REFER to the destination and exits the bridge.
                                # Charges stop at this point. No /transfer-status callbacks will arrive.
                                # SIP URI requires E.164 digits only (e.g. +14155551234).
                                # Extension is appended to the user part with DTMF pauses (,,ext).
                                digits_only = _re.sub(r"[^\d+]", "", phone_number)
                                sip_user = (
                                    f"{digits_only},,{extension}" if extension else digits_only
                                )
                                sip_uri = f"sip:{sip_user}@pstn.twilio.com"
                                twiml_parts.append(f"<Refer><Sip>{sip_uri}</Sip></Refer>")
                                twiml_parts.append("</Response>")
                                transfer_twiml = "\n".join(twiml_parts)

                                logger.info(
                                    f"🔄 Cold SIP REFER transfer for call {self.call_sid} to {phone_number} ({sip_uri})"
                                )
                                # Full TwiML XML is gated behind LOG_PROMPTS to keep prod logs clean.
                                if _should_log_prompts():
                                    logger.debug(f"Cold Transfer TwiML:\n{transfer_twiml}")
                            else:
                                # Warm Transfer (Twilio bridges both legs)
                                # Twilio stays in the call and bridges the caller to the new number.
                                # Status callbacks arrive at /transfer-status to track the second leg.
                                caller_id = self.to_number or os.environ.get(
                                    "TWILIO_PHONE_NUMBER", ""
                                )
                                if caller_id:
                                    twiml_parts.append(
                                        f'<Dial timeout="30" callerId="{caller_id}">'
                                    )
                                else:
                                    twiml_parts.append('<Dial timeout="30">')

                                base_url = get_public_base_url()
                                status_callback = f"{base_url}/api/calls/transfer-status"
                                send_digits_attr = (
                                    f' sendDigits="{extension_pause_commas}{extension}"'
                                    if extension
                                    else ""
                                )
                                twiml_parts.append(
                                    f'<Number statusCallback="{status_callback}" '
                                    f'statusCallbackEvent="initiated ringing answered completed"'
                                    f"{send_digits_attr}>"
                                    f"{phone_number}</Number>"
                                )
                                twiml_parts.append("</Dial>")
                                twiml_parts.append("</Response>")
                                transfer_twiml = "\n".join(twiml_parts)

                                logger.info(
                                    f"🔄 Warm transfer for call {self.call_sid} to {phone_number}"
                                )
                                # Full TwiML XML is gated behind LOG_PROMPTS to keep prod logs clean.
                                if _should_log_prompts():
                                    logger.debug(f"Warm Transfer TwiML:\n{transfer_twiml}")

                            # All DB + Twilio REST work runs in a single worker thread.
                            # Session opens here — no await crosses this boundary.
                            # _twilio_cap is the Twilio SDK client (stateless, thread-safe).
                            _call_sid_cap = self.call_sid
                            _twilio_cap = self.twilio_client

                            def _db_record_and_transfer():
                                from ..database import SessionLocal as _SL
                                from ..services.call_logger import CallLogger as _CL

                                db = _SL()
                                try:
                                    call_logger = _CL(db)
                                    if transfer_mode == "cold":
                                        call_logger.record_transfer(
                                            call_sid=_call_sid_cap,
                                            transfer_to=phone_number,
                                            transfer_type="cold",
                                        )
                                        _twilio_cap.calls(_call_sid_cap).update(
                                            twiml=transfer_twiml
                                        )
                                        # Twilio does NOT call /connect-complete after a REST API
                                        # <Refer> update, so ACW must be triggered here directly.
                                        try:
                                            from ..models import Assistant as _Assistant
                                            from ..services.acw_service import (
                                                run_acw_background as _run_acw_bg,
                                                should_auto_run_acw as _should_acw,
                                            )

                                            _call_log = call_logger.get_call_log(_call_sid_cap)
                                            if _call_log and _call_log.assistant_id:
                                                _asst = (
                                                    db.query(_Assistant)
                                                    .filter(_Assistant.id == _call_log.assistant_id)
                                                    .first()
                                                )
                                                if _should_acw(_asst, _call_sid_cap):
                                                    import threading

                                                    threading.Thread(
                                                        target=_run_acw_bg,
                                                        args=(_call_log.id,),
                                                        daemon=True,
                                                    ).start()
                                                    logger.info(
                                                        f"ACW background thread started for cold transfer call {_call_sid_cap}"
                                                    )
                                        except Exception as _acw_e:
                                            logger.error(
                                                f"Failed to start ACW thread after cold transfer: {_acw_e}"
                                            )
                                        # Twilio also skips /connect-complete for record
                                        # auto-extraction, so trigger it here too.
                                        try:
                                            from ..services.record_extraction_service import (
                                                has_active_extraction_types as _has_extract,
                                                run_record_extraction_for_call_in_thread as _run_extract,
                                            )

                                            _rec_call_log = call_logger.get_call_log(_call_sid_cap)
                                            if (
                                                _rec_call_log
                                                and _rec_call_log.account_id
                                                and _has_extract(
                                                    _rec_call_log.account_id,
                                                    _rec_call_log.assistant_id,
                                                    db,
                                                )
                                            ):
                                                import threading

                                                _rec_log_id = _rec_call_log.id
                                                threading.Thread(
                                                    target=_run_extract,
                                                    args=(_rec_log_id,),
                                                    daemon=True,
                                                ).start()
                                                logger.info(
                                                    f"Record extraction thread started for cold transfer call {_call_sid_cap}"
                                                )
                                        except Exception as _rec_e:
                                            logger.error(
                                                f"Failed to start record extraction thread after cold transfer: {_rec_e}"
                                            )
                                    else:
                                        call_logger.record_transfer(
                                            call_sid=_call_sid_cap,
                                            transfer_to=phone_number,
                                            transfer_type="warm",
                                        )
                                        _twilio_cap.calls(_call_sid_cap).update(
                                            twiml=transfer_twiml
                                        )
                                    return True
                                finally:
                                    db.close()

                            _transfer_succeeded = await _asyncio.to_thread(_db_record_and_transfer)
                            logger.info(
                                f"✅ {'Cold SIP REFER' if transfer_mode == 'cold' else 'Warm'} transfer "
                                f"initiated for call {self.call_sid} to {phone_number}"
                            )

                        except Exception as e:
                            if isinstance(e, _TwilioRestException) and e.status == 400:
                                # Race condition: Twilio returned 400 because the call leg
                                # was already terminated — this happens when the transfer
                                # completes so fast that by the time our REST update() call
                                # lands, Twilio has already ended the original leg.  Treat
                                # this as a clean transfer end so the pipeline closes
                                # gracefully rather than staying alive indefinitely.
                                logger.warning(
                                    f"⚠️ Twilio 400 on transfer REST call for {self.call_sid} — "
                                    f"call leg already ended (fast transfer race); treating as clean end"
                                )
                                _call_already_ended = True
                            else:
                                logger.error(
                                    f"❌ Twilio transfer failed for call {self.call_sid}: {e}"
                                )
                    else:
                        missing = []
                        if not self.twilio_client:
                            missing.append("Twilio client")
                        if not self.call_sid:
                            missing.append("call_sid")
                        logger.warning(f"⚠️ Cannot transfer call: missing {', '.join(missing)}")
                finally:
                    # Gate EndFrame on a confirmed successful Twilio update.
                    #
                    # SUCCESS (2xx): the transfer TwiML was accepted — end our
                    # pipeline now.  With auto_hang_up=False the WebSocket closes
                    # without a REST hangup, so Twilio executes <Dial>/<Refer>
                    # independently.  The synchronous calls().update() call above
                    # guarantees TwiML is submitted BEFORE this EndFrame fires.
                    #
                    # FAILURE (404 / exception / missing credentials): do NOT push
                    # EndFrame — leave the pipeline running so the AI can continue
                    # the conversation.  If the call is truly gone (404), Twilio
                    # will close the WebSocket on its side and the transport will
                    # push EndFrame naturally.
                    if _transfer_succeeded or _call_already_ended:
                        await params.llm.push_frame(EndFrame())
                    else:
                        logger.warning(
                            f"Transfer did not succeed for {self.call_sid} — "
                            f"EndFrame not pushed; pipeline remains active"
                        )

            # Record what will be spoken so _execute_transfer can append it to
            # the saved transcript (TTSSpeakFrame bypasses the LLM context).
            self._pending_pre_transfer_message = pre_message

            # WHY THE SLEEP: FunctionCallInProgressFrame arrives ~67ms after this
            # handler runs and wipes the active TTS context before Deepgram audio
            # returns (~125ms).  Sleeping 250ms (+ one event-loop yield) lets that
            # frame fully clear the stale context.  We then create a fresh named
            # context so the pre-transfer phrase has a valid landing zone and we
            # know exactly which context_id to bind our callback to.
            await _asyncio.sleep(0)
            await _asyncio.sleep(0.25)

            # Create a fresh TTS audio context and bind the transfer callback to it.
            # When on_audio_context_completed fires for this exact context_id the
            # transfer executes — immune to Deepgram's spurious mid-turn
            # BotStoppedSpeakingFrame.  Falls back to BotStopped watcher if the
            # TTS service does not expose create_audio_context.
            import uuid as _uuid

            _ctx_id: str | None = None
            if self._tts_service is not None and hasattr(self._tts_service, "create_audio_context"):
                _ctx_id = str(_uuid.uuid4())
                try:
                    await self._tts_service.create_audio_context(_ctx_id)
                    logger.debug(
                        f"Created fresh TTS audio context {_ctx_id} for transfer phrase "
                        f"on call {self.call_sid}"
                    )
                except Exception as _ctx_err:
                    logger.warning(
                        f"Failed to create TTS audio context for transfer phrase "
                        f"on call {self.call_sid}: {_ctx_err}"
                    )
                    _ctx_id = None

            # Register callback AFTER context creation so we know the exact ctx_id.
            # context_id=None falls through to BotStopped watcher (reset=True).
            self._run_after_speech(
                _execute_transfer,
                label="Transfer",
                reset=(_ctx_id is None),
                context_id=_ctx_id,
                speech_text=pre_message,
            )

            await params.llm.push_frame(TTSSpeakFrame(pre_message))

        return function_schema, transfer_handler

    def _extract_nested_value(self, data: Any, path: str) -> Any:
        """Extract a value from nested data using dot notation (e.g., 'data.guest.name'). Also supports JSONPath prefix ($.)."""
        if path.startswith("$."):
            path = path[2:]
        parts = path.replace("[", ".").replace("]", "").split(".")
        current = data
        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def _apply_response_mapping(
        self, data: Any, response_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """Apply response mapping to extract specific fields from API response."""
        result = {}
        for variable_name, json_path in response_mapping.items():
            value = self._extract_nested_value(data, json_path)
            result[variable_name] = value
        return result

    def _map_api_request(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map API request tool to Pipecat function.

        This allows AI to call external APIs during conversations.
        Parameters are extracted from the API config.
        Supports response mapping (extracting specific fields) and
        response instructions (telling the LLM how to present data).
        """
        parameters = tool.config.get("parameters", {})
        body_template = tool.config.get("body_template")
        response_mapping = tool.config.get("response_mapping") or tool.config.get("responseMapping") or {}
        response_instructions = tool.config.get("response_instructions", "")

        # Build function schema with parameters from config
        description = tool.description
        if response_instructions:
            description = f"{tool.description}\n\nWhen you receive the result, follow these instructions: {response_instructions}"

        function_schema = {
            "name": sanitize_function_name(tool.name),
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if v.get("required", False)],
            },
        }

        mapper = self

        async def api_handler(params: FunctionCallParams):
            """Execute API tool through the shared ActionExecutor."""
            from botelier.services.action_executor import (
                ActionContext,
                ActionExecutionRequest,
                ActionExecutor,
            )

            arguments = params.arguments
            if not mapper.db_session or not mapper.account_id:
                await params.result_callback(
                    {"error": "API tool requires account context", "status": "failed"}
                )
                return

            config = dict(tool.config or {})
            if "bodyTemplate" not in config and body_template:
                config["bodyTemplate"] = body_template
            result = await ActionExecutor(mapper.db_session).execute_and_log(
                ActionExecutionRequest(
                    context=ActionContext(
                        account_id=mapper.account_id,
                        channel="voice",
                        call_sid=mapper.call_sid,
                        tool_id=tool.id,
                        property_id=mapper.property_id,
                    ),
                    variables=arguments,
                    legacy_config=config,
                )
            )

            if result.success:
                await params.result_callback(
                    result.extracted_variables if response_mapping else result.data
                )
            else:
                await params.result_callback(
                    {
                        "error": result.error_message or "API request failed",
                        "status": "failed",
                        "error_type": result.error_type.value,
                        "status_code": result.status_code,
                    }
                )

        return function_schema, api_handler

    def _map_capability(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map a universal capability tool to a Pipecat function (Task #329).

        The schema (name/description/parameters) comes from the capability
        registry, so the LLM sees only the abstract capability — never the
        vendor. At call time the CapabilityResolver maps it to the caller's
        property-scoped provider connection and executes through the same
        ActionExecutor → IntegrationClient path, inheriting Task #327 fail-closed
        property gating and Task #328 canonical envelopes.
        """
        from botelier.services.capabilities import build_capability_schema, get_capability

        capability_name = (tool.config or {}).get("capability")
        spec = get_capability(capability_name)
        schema = build_capability_schema(capability_name) if spec else None

        if not spec or not schema:
            # Misconfigured capability tool — fail closed: expose a stub that
            # returns an explicit error instead of a callable to a non-existent
            # capability.
            fallback_schema = {
                "name": sanitize_function_name(tool.name),
                "description": tool.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            }

            async def unknown_handler(params: FunctionCallParams):
                await params.result_callback(
                    {"error": f"Unknown capability '{capability_name}'.", "status": "failed"}
                )

            return fallback_schema, unknown_handler

        response_instructions = (tool.config or {}).get("response_instructions", "")
        if response_instructions:
            schema = dict(schema)
            schema["description"] = (
                f"{schema['description']}\n\nWhen you receive the result, follow these "
                f"instructions: {response_instructions}"
            )

        mapper = self

        async def capability_handler(params: FunctionCallParams):
            """Resolve + execute the capability through the shared resolver."""
            from botelier.services.capabilities import CapabilityResolver

            if not mapper.db_session or not mapper.account_id:
                await params.result_callback(
                    {"error": "Capability requires account context", "status": "failed"}
                )
                return

            resolver = CapabilityResolver(
                mapper.db_session, mapper.account_id, mapper.property_id
            )
            result = await resolver.execute(
                capability_name,
                channel="voice",
                arguments=params.arguments,
                call_sid=mapper.call_sid,
            )
            await params.result_callback(result)

        return schema, capability_handler

    def _map_dynamic_operation(
        self, tool: Tool
    ) -> Optional[tuple[Dict[str, Any], Callable]]:
        """Map a DYNAMIC_OPERATION tool to a Pipecat function.

        DYNAMIC_OPERATION tools are published operations from an imported
        spec (OpenAPI / Postman) that have gone through the
        certified IntegrationClient pipeline (full property isolation,
        rate-limiting, circuit-breaker, credential encryption, response
        redaction).  The LLM sees only the LLM-owned parameters from the
        published action version's ``input_schema``; connection/secret/fixed
        params are injected at execution time by the runtime and are never
        visible to the model.

        Returns None when the backing connection is not CONNECTED or is
        property-scoped to a different property than this session — the tool
        must not appear in the LLM's schema list at all (3-channel parity with
        SMS / simulator which both use None returns to skip).
        """
        from botelier.models.integration import (
            AccountIntegration,
            IntegrationAction,
            IntegrationActionVersion,
            IntegrationStatus,
        )
        from botelier.services.action_executor import (
            ActionContext,
            ActionExecutionRequest,
            ActionExecutor,
        )
        from botelier.services.integration_client import IntegrationAPIConfig

        tool_config = tool.config or {}
        action_id = tool_config.get("integration_action_id")
        connection_id = tool_config.get("connection_id")
        operation_id = tool_config.get("operation_id")

        # Connection-status + property-scope gate — must happen BEFORE schema
        # construction so the tool is invisible to the LLM when unavailable.
        # Use session_factory when db_session is absent (live voice calls).
        if connection_id and (self.db_session is not None or self.session_factory is not None):
            _gate_db, _gate_owned = (
                (self.db_session, False)
                if self.db_session is not None
                else (self.session_factory(), True)
            )
            try:
                conn = _gate_db.query(AccountIntegration).filter(
                    AccountIntegration.id == connection_id
                ).first()
                if not conn or conn.status != IntegrationStatus.CONNECTED:
                    return None  # Disconnected — invisible to LLM
                # Property scope: account-global connections (property_id is NULL) are
                # always visible; property-bound connections are only shown for the
                # matching session property.
                if conn.property_id is not None:
                    session_prop = self.property_id
                    if session_prop is None or str(conn.property_id) != str(session_prop):
                        return None  # Wrong property scope — invisible to LLM
            finally:
                if _gate_owned:
                    _gate_db.close()

        # Build the function schema from the published action version's input_schema.
        # Fall back to an empty schema when the action hasn't been published yet
        # (fail closed: the tool appears but can never be called with invalid args).
        def _load_schema_and_config(db_session):
            if not action_id or not db_session:
                return None, None, None
            action = db_session.query(IntegrationAction).filter(IntegrationAction.id == action_id).first()
            if not action or not action.published_version_id:
                return None, None, None
            version = db_session.query(IntegrationActionVersion).filter(
                IntegrationActionVersion.id == action.published_version_id
            ).first()
            return action, version, version.config if version else None

        # Schema loading: use session_factory when db_session is absent (live voice calls).
        _schema_db, _schema_owned = (
            (self.db_session, False)
            if self.db_session is not None
            else (self.session_factory(), True)
            if self.session_factory is not None
            else (None, False)
        )
        try:
            action, version, exec_config = _load_schema_and_config(_schema_db)
        finally:
            if _schema_owned and _schema_db is not None:
                _schema_db.close()

        if version and version.input_schema:
            input_schema = version.input_schema
        else:
            input_schema = {"type": "object", "properties": {}, "required": []}

        function_schema = {
            "name": sanitize_function_name(tool.name),
            "description": tool.description or tool.name,
            "parameters": input_schema,
        }

        mapper = self

        async def dynamic_operation_handler(params: FunctionCallParams):
            """Execute a DYNAMIC_OPERATION through the certified integration runtime."""
            if not mapper.account_id:
                await params.result_callback(
                    {"error": "DYNAMIC_OPERATION requires account context", "status": "failed"}
                )
                return

            # Open a short-lived session from the factory when db_session is absent
            # (live voice calls); borrow the request session otherwise (simulator).
            _exec_db, _exec_owned = (
                (mapper.db_session, False)
                if mapper.db_session is not None
                else (mapper.session_factory(), True)
                if mapper.session_factory is not None
                else (None, False)
            )
            if _exec_db is None:
                await params.result_callback(
                    {"error": "DYNAMIC_OPERATION requires account context", "status": "failed"}
                )
                return

            try:
                _action, _version, _exec_config = _load_schema_and_config(_exec_db)

                if not _version or not _exec_config:
                    await params.result_callback(
                        {"error": f"Operation {operation_id!r} has no published version", "status": "failed"}
                    )
                    return

                # Shared builder (same one test_operation and every other channel
                # uses) so the executed request shape — including persisted
                # request_overrides — matches what was tested.
                from botelier.services.operation_publisher import build_operation_api_config

                config = build_operation_api_config(
                    _exec_config,
                    fallback_integration_id=connection_id or "",
                    fallback_endpoint_id=operation_id or "",
                )

                # Broad catch (parity with the SMS channel): an unexpected executor
                # exception must surface as a tool-result error the LLM can speak
                # around — never propagate and kill the voice tool turn mid-call.
                try:
                    result = await ActionExecutor(_exec_db).execute_and_log(
                        ActionExecutionRequest(
                            context=ActionContext(
                                account_id=mapper.account_id,
                                channel="voice",
                                call_sid=mapper.call_sid,
                                tool_id=tool.id,
                                property_id=mapper.property_id,
                            ),
                            variables=params.arguments,
                            integration_config=config,
                            response_policy=_exec_config.get("response_policy") if _exec_config else None,
                        )
                    )
                except Exception as exc:
                    logger.error(f"DYNAMIC_OPERATION voice tool error: {exc}")
                    await params.result_callback(
                        {"error": "Dynamic operation failed", "status": "failed"}
                    )
                    return
            finally:
                if _exec_owned:
                    _exec_db.close()

            if result.success:
                # When response_mapping is defined, return only the projected
                # fields so the LLM never sees the full raw response body.
                # Always use extracted_variables when projections are configured
                # (even if extraction yields {}) — never fall back to raw data.
                if config.response_variables:
                    await params.result_callback(result.extracted_variables or {})
                else:
                    await params.result_callback(result.data)
            else:
                await params.result_callback(
                    {
                        "error": result.error_message or "Dynamic operation failed",
                        "status": "failed",
                        "error_type": result.error_type.value if result.error_type else "unknown",
                        "status_code": result.status_code,
                    }
                )

        return function_schema, dynamic_operation_handler

    def _map_end_call(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map end call tool to Pipecat function."""
        goodbye_message = tool.config.get("goodbye_message", "Thank you for calling. Goodbye!")

        function_schema = {
            "name": sanitize_function_name(tool.name),
            # Append a firm instruction to suppress LLM-generated text alongside this
            # tool call.  Without it the model emits a spoken farewell (e.g. "Goodbye!")
            # AND the handler pushes TTSSpeakFrame(goodbye_message), producing double
            # audio.  The farewell is handled entirely by the handler — the LLM must
            # only call the function and return an empty assistant message.
            "description": (
                tool.description
                + " When calling this function, do not generate any spoken text"
                " — the farewell message is handled automatically."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }

        async def end_call_handler(params: FunctionCallParams):
            """End the call gracefully — AFTER the goodbye is fully heard.

            Same decoupled pattern as transfer_handler: register a post-speech
            callback on TtsCompletionWatcher, push the goodbye TTSSpeakFrame,
            and return immediately.  The callback (_finalize_call_end) fires
            once BotStoppedSpeakingFrame arrives, awaits a Twilio playback mark
            (proof the caller heard the buffered audio), and only THEN issues
            the REST hangup + EndFrame.  Previously the REST hangup was issued
            immediately after pushing the TTSSpeakFrame, which killed the phone
            leg before the goodbye played.

            IMPORTANT: Do NOT call result_callback here.  Calling it feeds the
            function result back into the LLM, triggering a new generation cycle.
            On that extra cycle the LLM sees remaining tools (e.g. Transfer) and
            can call them after the goodbye has already been spoken — exactly the
            "transfer after goodbye" bug.  See transfer_handler for the same
            reasoning and the authoritative comment.
            """
            import asyncio as _asyncio

            self.track_tool_usage(tool.name)

            async def _finalize_end_call():
                await self._finalize_call_end(
                    params.llm, "end_call", speech_text=goodbye_message
                )

            # Yield to let FunctionCallInProgressFrame clear the TTS context
            # before we push TTSSpeakFrame (arrives ~67ms later and wipes the
            # context; 250ms sleep lets it finish first).  Then create a fresh
            # named context so _run_after_speech can bind the hangup to that
            # exact context-ID.  The context-ID path now uses a two-stage chain:
            # on_audio_context_completed → TtsCompletionWatcher.schedule_after_speech
            # → BotStoppedSpeakingFrame, which fires only after audio bytes are
            # confirmed written to the Twilio WebSocket.  Falls back to watcher/
            # delay if the TTS service does not expose create_audio_context.
            await _asyncio.sleep(0)
            await _asyncio.sleep(0.25)

            import uuid as _uuid

            _ctx_id: str | None = None
            if self._tts_service is not None and hasattr(self._tts_service, "create_audio_context"):
                _ctx_id = str(_uuid.uuid4())
                try:
                    await self._tts_service.create_audio_context(_ctx_id)
                    logger.debug(
                        f"Created fresh TTS audio context {_ctx_id} for goodbye phrase "
                        f"on call {self.call_sid}"
                    )
                except Exception as _ctx_err:
                    logger.warning(
                        f"Failed to create TTS audio context for goodbye phrase "
                        f"on call {self.call_sid}: {_ctx_err}"
                    )
                    _ctx_id = None

            self._run_after_speech(
                _finalize_end_call,
                label="End-call",
                reset=(_ctx_id is None),
                context_id=_ctx_id,
                speech_text=goodbye_message,
            )
            await params.llm.push_frame(TTSSpeakFrame(goodbye_message))

        return function_schema, end_call_handler

    def _map_send_sms(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send SMS tool to Pipecat function.

        Sends an SMS to the caller's number using the account's Twilio
        sub-account credentials (or platform defaults as fallback).

        The LLM may pass a ``message`` argument with the full SMS body (ideal
        for dynamic content like checkout URLs).  When omitted, the tool falls
        back to the static ``message_body`` template configured on the tool,
        which supports these placeholders:
          {caller_number}  — the inbound caller's E.164 number
          {caller_name}    — caller name if available, otherwise "Caller"
          {account_name}   — the business name from the account record

        Placeholders are applied to both the dynamic message and the template
        so static templates can still personalise the message.
        """
        message_body_template: str = (tool.config or {}).get("message_body", "")

        function_schema = {
            "name": sanitize_function_name(tool.name),
            "description": (
                tool.description
                or "Send an SMS text message to the caller. "
                "Use this whenever the caller needs a link, URL, checkout page, "
                "or any information that should not be read aloud on a phone call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "The full SMS body to send to the caller. "
                            "Include any URLs or links here — do NOT read them aloud. "
                            "Example: 'Here is your checkout link: https://example.com/cart/abc123'. "
                            "If omitted, the pre-configured default message is sent."
                        ),
                    }
                },
                "required": [],
            },
        }

        mapper = self

        async def send_sms_handler(params: FunctionCallParams):
            mapper.track_tool_usage(tool.name)

            caller_number = mapper.from_number or ""
            business_number = mapper.to_number or ""

            if not caller_number:
                logger.warning(
                    f"[send_sms] No caller number available for call {mapper.call_sid}; skipping send"
                )
                await params.result_callback({"status": "skipped", "reason": "no caller number"})
                return

            if not mapper.twilio_client:
                logger.warning(
                    f"[send_sms] No Twilio client available for call {mapper.call_sid}; skipping send"
                )
                await params.result_callback({"status": "skipped", "reason": "no twilio credentials"})
                return

            account_name = mapper.account_name or "Business"

            # Dynamic message from the LLM takes priority over the static template.
            # This allows the LLM to send checkout URLs, product links, etc. that it
            # received from a tool result — without reading them aloud over the phone.
            dynamic_message: str = ((params.arguments or {}).get("message") or "").strip()
            body = dynamic_message if dynamic_message else message_body_template

            # Apply template placeholders on both paths so personalisation works
            # whether the LLM provides a message or the static template is used.
            body = body.replace("{caller_number}", caller_number)
            body = body.replace("{caller_name}", "Caller")
            body = body.replace("{account_name}", account_name)

            if not body:
                logger.warning(
                    f"[send_sms] Empty message body for call {mapper.call_sid}; skipping send"
                )
                await params.result_callback({"status": "skipped", "reason": "empty message body"})
                return

            try:
                message = mapper.twilio_client.messages.create(
                    body=body,
                    from_=business_number,
                    to=caller_number,
                )
                logger.info(
                    f"[send_sms] Sent SMS {message.sid} from {business_number} to {caller_number} "
                    f"on call {mapper.call_sid}"
                    + (" [dynamic]" if dynamic_message else " [template]")
                )
                await params.result_callback({"status": "sent", "message_sid": message.sid})
            except Exception as exc:
                logger.exception(
                    f"[send_sms] Failed to send SMS on call {mapper.call_sid}: {exc}"
                )
                await params.result_callback({"status": "failed", "reason": str(exc)})

        return function_schema, send_sms_handler

    def _map_send_email(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send email tool to Pipecat function.

        Sends an email via SendGrid on behalf of the account. The LLM must
        supply the recipient's ``to`` address and the complete ``message``
        body (obtained or composed however it likes — from the caller, an
        API result, a flow variable, or conversation context). ``subject``
        is optional and falls back to the configured default.

        Sender identity resolution order:
          1. Tool-level ``from_email`` / ``from_name`` in config (rare override)
          2. Account-level ``email_from`` / ``email_from_name`` DB columns
          3. Platform defaults from EMAIL_FROM_DEFAULT / EMAIL_FROM_NAME_DEFAULT

        """
        cfg = tool.config or {}
        default_subject: str = cfg.get("default_subject", "")
        message_body_template: str = cfg.get("message_body", "")
        # Optional per-tool sender override (most accounts won't set this)
        tool_from_email: str = cfg.get("from_email", "")
        tool_from_name: str = cfg.get("from_name", "")

        function_schema = {
            "name": sanitize_function_name(tool.name),
            "description": (
                tool.description
                or "Send an email to a recipient. "
                "Use this to deliver requested information, links, summaries, "
                "or any other content that should be sent by email. "
                "You must obtain the recipient's email address before calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": (
                            "Recipient email address. You must have this value before "
                            "calling the tool — ask the caller if you don't have it."
                        ),
                    },
                    "subject": {
                        "type": "string",
                        "description": (
                            "Email subject line. If omitted, the pre-configured "
                            "default subject is used."
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "Full email body to send. This is required. Compose it "
                            "from the conversation context and include any requested "
                            "URLs, links, or details here — do NOT read URLs aloud "
                            "on the call."
                        ),
                    },
                },
                "required": ["to", "message"],
            },
        }

        mapper = self

        async def send_email_handler(params: FunctionCallParams):
            mapper.track_tool_usage(tool.name)

            args = params.arguments or {}
            to_address: str = (args.get("to") or "").strip()
            dynamic_subject: str = (args.get("subject") or "").strip()
            dynamic_message: str = (args.get("message") or "").strip()

            if not to_address:
                logger.warning(
                    "[send_email] LLM did not provide a 'to' address for call %s; skipping",
                    mapper.call_sid,
                )
                await params.result_callback(
                    {"status": "skipped", "reason": "no recipient email address provided"}
                )
                return

            # Resolve effective subject — LLM value wins over config default
            effective_subject = dynamic_subject or default_subject or "Message from " + (mapper.account_name or "us")

            # The function schema requires the LLM to provide the complete
            # body. Preserve the configured template only as a compatibility
            # fallback for existing records or non-LLM/manual callers.
            account_name = mapper.account_name or "Business"
            effective_body = dynamic_message or message_body_template.replace(
                "{account_name}", account_name
            )

            if not effective_body:
                logger.warning(
                    "[send_email] Empty message body for call %s; skipping send",
                    mapper.call_sid,
                )
                await params.result_callback(
                    {"status": "skipped", "reason": "empty message body"}
                )
                return

            # ── Connected email sender path ──────────────────────────────────
            # When the tool is configured with a specific connected sender
            # (Gmail / Microsoft), route through that account instead of the
            # legacy SendGrid path.  Failures are reported to the LLM as a
            # tool result so the caller hears a clear error rather than silence.
            connection_id = cfg.get("connection_id", "").strip()
            if connection_id:
                from botelier.models.integration import AccountIntegration as _AI
                from botelier.services.email_service import (
                    send_email_via_connection as _send_via_conn,
                )
                from sqlalchemy.orm import joinedload as _jl

                def _do_send_connected():
                    _db_session = getattr(mapper, "db_session", None)

                    def _run(db):
                        _conn = (
                            db.query(_AI)
                            .options(_jl(_AI.integration_type))
                            .filter(_AI.id == uuid.UUID(connection_id))
                            .first()
                        )
                        if not _conn:
                            raise ValueError(
                                "The configured email sender was not found. "
                                "Please reconfigure the SEND_EMAIL tool in Settings."
                            )
                        return _send_via_conn(
                            _conn,
                            to_addresses=[to_address],
                            subject=effective_subject,
                            body_text=effective_body,
                        )

                    if _db_session is not None:
                        return _run(_db_session)
                    if mapper.session_factory:
                        with mapper.session_factory() as _db:
                            return _run(_db)
                    raise ValueError("No database session available for email send.")

                try:
                    _ok = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, _do_send_connected),
                        timeout=30.0,
                    )
                    if _ok:
                        logger.info(
                            "[send_email] Sent via connected account to %s on call %s",
                            to_address,
                            mapper.call_sid,
                        )
                        await params.result_callback(
                            {"status": "sent", "to": to_address, "subject": effective_subject}
                        )
                    else:
                        await params.result_callback(
                            {"status": "failed", "reason": "email delivery failed via connected account"}
                        )
                except asyncio.TimeoutError:
                    await params.result_callback(
                        {"status": "failed", "reason": "email delivery timed out"}
                    )
                except ValueError as _ve:
                    logger.warning("[send_email] Connected sender error: %s", _ve)
                    await params.result_callback({"status": "failed", "reason": str(_ve)})
                except Exception as _exc:
                    logger.error("[send_email] Connected sender unexpected error: %s", _exc)
                    await params.result_callback(
                        {"status": "failed", "reason": "unexpected error during email delivery"}
                    )
                return
            # ── End connected email sender path ──────────────────────────────

            # Resolve sender — tool config → account DB → platform env default
            resolved_from_email = tool_from_email or None
            resolved_from_name = tool_from_name or None

            if not resolved_from_email and mapper.account_id:
                try:
                    from ..models.account import Account

                    # Prefer an already-open session (simulator / API contexts);
                    # fall back to session_factory for live voice calls where
                    # db_session is None (closed before the call pipeline starts).
                    _existing_db = getattr(mapper, "db_session", None)
                    if _existing_db is not None:
                        acc = _existing_db.query(Account).filter(Account.id == mapper.account_id).first()
                        if acc:
                            resolved_from_email = acc.email_from or None
                            resolved_from_name = resolved_from_name or acc.email_from_name or None
                    elif mapper.session_factory:
                        with mapper.session_factory() as _db:
                            acc = _db.query(Account).filter(Account.id == mapper.account_id).first()
                            if acc:
                                resolved_from_email = acc.email_from or None
                                resolved_from_name = resolved_from_name or acc.email_from_name or None
                except Exception as _acc_err:
                    logger.warning(
                        "[send_email] Could not look up account sender config for %s: %s",
                        mapper.account_id,
                        _acc_err,
                    )

            # email_service falls back to EMAIL_FROM_DEFAULT if resolved_from_email is None.
            # Run the synchronous SendGrid HTTP call in a worker thread so it cannot
            # block the Pipecat voice event loop while waiting on a slow API response.
            # A 30-second timeout caps the worst case (network hang, SendGrid outage).
            from botelier.services.email_service import send_email as _send_email

            try:
                success = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: _send_email(
                            to_addresses=[to_address],
                            subject=effective_subject,
                            body_text=effective_body,
                            from_email=resolved_from_email,
                            from_name=resolved_from_name,
                        ),
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[send_email] SendGrid request timed out after 30s for call %s to %s",
                    mapper.call_sid,
                    to_address,
                )
                await params.result_callback(
                    {"status": "failed", "reason": "email delivery timed out"}
                )
                return

            if success:
                logger.info(
                    "[send_email] Sent email to %s (subject: '%s') on call %s",
                    to_address,
                    effective_subject,
                    mapper.call_sid,
                )
                await params.result_callback(
                    {"status": "sent", "to": to_address, "subject": effective_subject}
                )
            else:
                logger.warning(
                    "[send_email] Delivery failed for call %s to %s",
                    mapper.call_sid,
                    to_address,
                )
                await params.result_callback(
                    {"status": "failed", "reason": "email delivery failed — check SENDGRID_API_KEY and sender config"}
                )

        return function_schema, send_email_handler

    def _map_flow(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map a conversation flow tool to Pipecat function.

        Flows are visual conversation workflows with nodes for:
        - Collecting slot information (name, dates, phone, etc.)
        - Making API requests
        - Conditional branching
        - Transferring calls
        - Ending conversations

        The flow executor converts the visual flow into function schemas
        that the LLM can call to progress through the flow.
        """
        flow_config_dict = tool.config or {}

        # Parse the flow configuration
        if not flow_config_dict.get("nodes"):
            logger.warning(f"Flow tool {tool.name} has no nodes configured")
            # Return a placeholder schema
            return {
                "name": sanitize_function_name(tool.name),
                "description": tool.description or "Execute conversation flow",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }, self._create_empty_flow_handler(tool.name)

        # Parse the flow config into typed objects
        flow_config = parse_flow_config(flow_config_dict)

        # Create flow executor with db context for integration API calls.
        # On live voice calls db_session=None; session_factory lets the executor
        # open its own short-lived sessions per API node execution.
        executor = FlowExecutor(
            flow_config,
            db_session=self.db_session,
            account_id=self.account_id,
            flow_tool_id=str(tool.id),
            call_sid=self.call_sid,
            property_id=self.property_id,
            session_factory=self.session_factory,
            call_context=self._flow_context,
            assistant_timezone=self.assistant_timezone,
        )

        # IMPORTANT: do NOT store this executor in _flow_executors.
        #
        # The authoritative executor for a live call is created (and optionally
        # rehydrated from a reconnect snapshot) inside get_flow_functions().
        # If _map_flow() stored its executor here, two bugs could silently occur:
        #
        #   A. map_tool_to_function() runs before get_flow_functions():
        #      get_flow_functions() finds the pre-stored executor and reuses it
        #      (line 2039), skipping rehydrate_from_snapshot() → reconnected
        #      callers lose their flow progress.
        #
        #   B. get_flow_functions() runs before map_tool_to_function():
        #      _map_flow() overwrites the rehydrated executor with a fresh
        #      one → same loss of progress.
        #
        # _llm_override is already stamped by get_flow_functions() at line 2071
        # for every executor it creates, so omitting it here is safe.
        # The executor below is ephemeral — used only to build the schema.

        # Return main flow trigger function
        # The LLM calls this when it detects the guest wants to start this flow
        function_schema = {
            "name": f"start_{sanitize_function_name(tool.name)}",
            "description": (
                f"Start the {tool.name} flow. {tool.description or ''} "
                "Call this IMMEDIATELY, in the same turn the customer expresses that intent — "
                "do NOT ask the customer any questions first. All parameters are optional: pass "
                "only details the customer has already volunteered; the flow itself collects "
                "everything else in order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    var.key: executor._create_slot_function(var)["function"]["parameters"][
                        "properties"
                    ][var.key]
                    for var in executor.flow_config.variables
                },
                "required": [],
                "additionalProperties": False,
            },
        }

        async def flow_trigger_handler(params: FunctionCallParams):
            """Stub — non-empty flows MUST go through get_flow_functions().

            This handler is returned by _map_flow() / map_tool_to_function() but
            MUST NEVER fire during a live call.  get_flow_functions() registers the
            correct _create_flow_trigger_handler() closure (with run_llm=False,
            duplicate-start guard, snapshot rehydration, and tool rebuild) as the
            live handler.  If this stub fires it means the registration order broke
            and the LLM received a stale, wrong start trigger.

            The stub logs a prominent error so the bug is immediately visible in
            production logs and returns a soft error to the caller rather than
            silently running the wrong greeting/greeting-less code path.
            """
            logger.error(
                f"Legacy _map_flow trigger fired for non-empty flow {tool.name!r}. "
                "Expected _create_flow_trigger_handler() to be registered by "
                "get_flow_functions(). Check tool registration order in call_handler."
            )
            await params.result_callback(
                {
                    "status": "error",
                    "message": "Unable to start this flow right now — please try again.",
                }
            )

        return function_schema, flow_trigger_handler

    def _create_empty_flow_handler(self, flow_name: str):
        """Create a placeholder handler for empty flows."""

        async def empty_handler(params: FunctionCallParams):
            await params.result_callback(
                {"status": "error", "message": f"Flow {flow_name} has no configured steps"}
            )

        return empty_handler

    def get_flow_functions(self, tool: Tool) -> tuple[list[Dict[str, Any]], Dict[str, Callable]]:
        """Get all function schemas and handlers for a flow tool.

        A flow generates multiple functions:
        - One trigger function to start the flow
        - One function per variable to collect
        - API request functions
        - Transfer and end call functions

        The executor is stored and reused across calls to maintain state
        throughout the conversation.

        Returns:
            Tuple of (list of function schemas, dict of handlers)
        """
        flow_config_dict = tool.config or {}
        tool_name = str(tool.name)
        safe_name = sanitize_function_name(tool_name)
        if safe_name != tool_name:
            logger.warning(
                f"Flow tool '{tool_name}' (id={getattr(tool, 'id', '?')}) has a name that "
                f"requires sanitization for the OpenAI API. It will be sent as 'start_{safe_name}'. "
                "Consider renaming the tool to use only letters, digits, spaces, hyphens, "
                "and underscores to suppress this warning."
            )

        if not flow_config_dict.get("nodes"):
            # Empty flow - return just the trigger function
            schema, handler = self._map_flow(tool)
            return [schema], {schema["name"]: handler}

        # Check if we already have an executor for this flow (state persistence)
        if tool_name in self._flow_executors:
            executor = self._flow_executors[tool_name]
            logger.debug(f"Reusing existing FlowExecutor for {tool_name}")
        else:
            # Parse and create new executor with db context for integration API calls.
            # On live voice calls db_session=None; session_factory lets the executor
            # open its own short-lived sessions per API node execution.
            flow_config = parse_flow_config(dict(flow_config_dict))
            executor = FlowExecutor(
                flow_config,
                db_session=self.db_session,
                account_id=self.account_id,
                flow_tool_id=str(tool.id),
                call_sid=self.call_sid,
                escalation_target=self.escalation_target,
                property_id=self.property_id,
                session_factory=self.session_factory,
                call_context=self._flow_context,
                assistant_timezone=self.assistant_timezone,
                flow_version_id=(
                    str(tool.published_version_id)
                    if getattr(tool, "published_version_id", None)
                    else None
                ),
            )
            # Task #330 — resume a dropped call. If this contact already has a
            # durable snapshot for this flow (websocket dropout + reconnect on a
            # fresh worker), restore its node + collected slots so the caller
            # picks up where they left off instead of starting over.
            try:
                if executor.rehydrate_from_snapshot():
                    logger.info(f"Resumed FlowExecutor for {tool_name} from snapshot")
            except Exception as exc:  # noqa: BLE001 - resume is best-effort
                logger.warning(f"Flow resume failed for {tool_name} (non-fatal): {exc}")
            self._flow_executors[tool_name] = executor
            logger.info(f"Created new FlowExecutor for {tool_name}")
            # Task #477 — stash per-flow LLM overrides for call_handler.
            executor._llm_override = {
                "llm_provider": getattr(tool, "llm_provider", None),
                "llm_model": getattr(tool, "llm_model", None),
                "llm_temperature": getattr(tool, "llm_temperature", None),
                "llm_max_tokens": getattr(tool, "llm_max_tokens", None),
            }

        # Get ALL function schemas for handler registration (so all handlers exist)
        all_function_schemas = executor.get_all_function_schemas()

        # Create handlers for ALL functions (handlers must exist for any function LLM might call)
        handlers = {}
        for schema in all_function_schemas:
            func_name = schema["function"]["name"]
            handlers[func_name] = self._create_flow_function_handler(tool_name, func_name)

        # Get current function schemas for initial tool exposure (only current slot)
        function_schemas = executor.get_function_schemas()

        # Add a start trigger only when this executor has not already entered
        # the graph (including a durable reconnect). Started flows expose only
        # the function valid at their current node.
        if not self._flow_has_started(executor):
            safe_tool_name = sanitize_function_name(tool_name)
            trigger_properties = {
                var.key: executor._create_slot_function(var)["function"]["parameters"][
                    "properties"
                ][var.key]
                for var in executor.flow_config.variables
            }
            trigger_schema = {
                "type": "function",
                "function": {
                    "name": f"start_{safe_tool_name}",
                    "description": (
                        f"Start the {tool_name} conversation flow when the customer wants to "
                        f"{tool.description or 'complete this task'}. Call this IMMEDIATELY, in the "
                        "same turn the customer expresses that intent — do NOT ask the customer any "
                        "questions first. All parameters are optional: pass only details the customer "
                        "has already volunteered; the flow itself collects everything else in order."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": trigger_properties,
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            }
            function_schemas.insert(0, trigger_schema)
            handlers[f"start_{safe_tool_name}"] = self._create_flow_trigger_handler(tool_name)

        return function_schemas, handlers

    def _create_flow_function_handler(self, tool_name: str, function_name: str):
        """Create a handler for a specific flow function.

        Uses tool_name to look up the stored executor, ensuring state
        is preserved across multiple function calls during a conversation.
        """

        async def handler(params: FunctionCallParams):
            # Look up the stored executor for this flow
            executor = self._flow_executors.get(tool_name)
            if not executor:
                logger.error(f"No executor found for flow {tool_name}")
                await params.result_callback({"status": "error", "message": "Flow not initialized"})
                return

            # Remember the flow position before the call so we can detect whether
            # this function advanced the flow and therefore requires a tool refresh.
            _prev_node_id = executor.state.current_node_id

            # Start API execution as a task so TTS can fire while it runs.
            api_task = asyncio.create_task(
                executor.handle_function_call(function_name, dict(params.arguments))
            )

            # Emit thinking message concurrently — before the HTTP call returns.
            _node_id = function_name.replace("execute_", "", 1)
            _api_node = next(
                (n for n in executor.flow_config.nodes if n.id == _node_id), None
            )
            _completed_api_node = _api_node
            if _api_node:
                _thinking = (_api_node.data.get("api", {}).get("thinkingMessage") or "").strip()
                if _thinking:
                    if hasattr(params, "llm") and params.llm is not None:
                        try:
                            await params.llm.push_frame(TTSSpeakFrame(text=_thinking))
                            self._capture_direct_speech(_thinking)
                            logger.debug(f"🗣️ Thinking message for {tool_name}: {_thinking!r}")
                        except Exception as _tm_err:
                            logger.warning(f"Could not emit thinking message for {tool_name}: {_tm_err}")
                    else:
                        logger.debug(f"No LLM context to emit thinking message for {tool_name}")

            result = await api_task
            result.pop("thinking_message", None)

            # Log collected data for debugging
            if result.get("collected"):
                logger.info(f"Flow {tool_name} collected: {result['collected']}")

            # If this call just advanced the flow onto an API node, do not
            # wait for the LLM to volunteer the newly-exposed execute_*
            # function. That leaves live callers in silence when the
            # post-function completion does not run. This used to only fire
            # after slot collection, but set_variable / router / confirmation
            # / save_record nodes can advance straight onto an API node too —
            # same silent-hang risk, same fix. POST/PUT/PATCH/DELETE nodes are
            # already guarded by FlowExecutor's per-node idempotency
            # locks/cache, so re-checking here is always safe.
            _current_node = executor.state.get_current_node()
            _advanced = executor.state.current_node_id != _prev_node_id
            if (
                _advanced
                and _current_node
                and _current_node.type == NodeType.API_REQUEST
            ):
                _api_function = f"execute_{_current_node.id}"
                _thinking = (
                    _current_node.data.get("api", {}).get("thinkingMessage") or ""
                ).strip()
                if _thinking and hasattr(params, "llm") and params.llm is not None:
                    await params.llm.push_frame(TTSSpeakFrame(text=_thinking))
                    self._capture_direct_speech(_thinking)
                logger.info(
                    f"▶️ Running pending API node for flow {tool_name} immediately "
                    f"after collection: {_api_function}"
                )
                result = await executor.handle_function_call(_api_function, {})
                _completed_api_node = _current_node

            # ── API_RESPONSE auto-execution ──────────────────────────────────
            # If the flow just landed on an API_RESPONSE node (from the direct
            # execute_ call or from the chained API_REQUEST above), render the
            # narration text now, speak it directly, and advance past the node.
            # This suppresses any further bridge / LLM narration turn since the
            # API_RESPONSE node owns all post-fetch speech.
            _current_node_now = executor.state.get_current_node()
            _api_response_spoke = False
            if _current_node_now and _current_node_now.type == NodeType.API_RESPONSE:
                _resp_text = executor._render_api_response_text(_current_node_now)
                if _resp_text and hasattr(params, "llm") and params.llm is not None:
                    try:
                        await params.llm.push_frame(TTSSpeakFrame(text=_resp_text))
                        self._capture_direct_speech(_resp_text)
                        logger.info(
                            f"🗣️ API_RESPONSE node spoke directly for {tool_name}: "
                            f"{_resp_text[:80]!r}"
                        )
                        _api_response_spoke = True
                    except Exception as _resp_err:
                        logger.warning(
                            f"Could not speak API_RESPONSE text for {tool_name}: {_resp_err}"
                        )
                # Advance the flow regardless of TTS success.
                try:
                    await executor.handle_function_call(
                        f"continue_response_{_current_node_now.id}", {}
                    )
                except Exception as _adv_err:
                    logger.warning(
                        f"Could not advance past API_RESPONSE node for {tool_name}: {_adv_err}"
                    )

            # The lookup's detailed presentation still comes from the LLM: its
            # response instructions may contain structured data that must not be
            # read verbatim.  However, the thinking message above is spoken
            # directly while the request runs, and a missing/cancelled LLM
            # continuation used to leave callers stranded after hearing it.
            # Give callers an immediate, safe completion bridge as soon as an API
            # result is available.  The function result remains in the LLM
            # context, so it can then present the mapped result naturally.
            # Look ahead: will this result already produce direct caller-facing
            # speech (a next collect prompt or a speak_directly message)? If so
            # the caller is not at risk of silence and the success bridge below
            # must NOT stack a second transition line on top (Task #547 — the
            # doubled "I've completed that check…" narration).
            _next_slot_preview = result.get("next_slot") or {}
            _will_speak_directly = bool(
                (result.get("collected") and str(_next_slot_preview.get("prompt") or "").strip())
                or (
                    # Mirrors the speak_directly gate below exactly — after an
                    # API node the direct-response path is disabled, so it must
                    # not count as guaranteed speech here either.
                    not _completed_api_node
                    and result.get("speak_directly")
                    and str(result.get("speak_exactly") or result.get("message") or "").strip()
                )
            )

            # Tracks whether the API result itself was spoken directly here,
            # so _spoke_directly below starts True and run_llm=False is used.
            # _api_response_spoke is True when the API_RESPONSE auto-execution
            # block above already spoke the narration directly.
            _api_spoke_directly = _api_response_spoke
            if _completed_api_node:
                _api_config = _completed_api_node.data.get("api", {}) or {}
                # voice_result is either designer-authored responseInstructions
                # (with {{variable}} subs) — genuine caller-facing narration —
                # or, when that's blank, an auto-built "success_msg + extracted
                # field: value" digest.  The digest is LLM CONTEXT ONLY: it is a
                # raw internal data dump ("Extracted data — room_price: 8000,
                # 7500; ...") and must never be spoken to a caller verbatim
                # (Task #601). voice_result_is_auto_summary distinguishes the
                # two so only genuine designer narration is ever pushed to TTS
                # here; the digest still reaches the LLM via result["result"]
                # below so it can narrate the data naturally on its own turn.
                _voice_result = str(result.get("voice_result") or "").strip()
                _voice_result_is_auto_summary = bool(result.get("voice_result_is_auto_summary"))
                if result.get("success"):
                    # Do not infer an outcome from transport success: an
                    # availability search with no rooms is still a successful
                    # API request. The LLM receives the mapped result and
                    # presents the actual availability outcome next.
                    #
                    # Task #547 — the success bridge is a silence safety net,
                    # not designer content: it is per-node configurable via
                    # api.onComplete (empty string suppresses it) and skipped
                    # entirely when the result already speaks directly.
                    if _will_speak_directly:
                        # Direct speech is guaranteed — never stack a bridge
                        # (default OR configured) on top of it.
                        _completion_bridge = ""
                    elif _voice_result and not _voice_result_is_auto_summary:
                        # Genuine designer narration.  Speak it immediately
                        # rather than a generic bridge followed by an LLM turn.
                        # Without this the LLM tends to skip narrating voice_result
                        # and calls the next flow tool directly, leaving callers
                        # hearing only the thinking message and never the actual
                        # availability/result data they asked for.
                        # Setting _api_spoke_directly=True propagates to
                        # _spoke_directly below, which selects run_llm=False and
                        # prevents a second LLM turn from repeating the narration.
                        _completion_bridge = ""
                        if hasattr(params, "llm") and params.llm is not None:
                            try:
                                await params.llm.push_frame(TTSSpeakFrame(text=_voice_result))
                                self._capture_direct_speech(_voice_result)
                                logger.info(
                                    f"🗣️ Spoke API result directly for {tool_name}: "
                                    f"{_voice_result[:80]!r}"
                                )
                                _api_spoke_directly = True
                            except Exception as _vr_err:
                                logger.warning(
                                    f"Could not emit API result for {tool_name}: {_vr_err}"
                                )
                    else:
                        # No narrable (speakable) data — either nothing was
                        # returned, or the only thing available is the raw
                        # extracted-data digest, which must stay LLM-context-only.
                        # Fall back to the configurable bridge so the caller at
                        # least hears that the check completed, then let a real
                        # LLM turn narrate the data (result["result"] still
                        # carries it — see the cleanup block below).
                        _on_complete = _api_config.get("onComplete")
                        _completion_bridge = (
                            "I've completed that check. Let me walk you through what I found."
                            if _on_complete is None
                            else str(_on_complete).strip()
                        )
                else:
                    _completion_bridge = str(
                        _api_config.get("onError")
                        or "I'm sorry, I wasn't able to complete that check. Please try again."
                    ).strip()
                    # Surface the real failure reason (status code + raw
                    # provider error) into the call's event timeline so an
                    # operator reviewing the call afterward can see e.g.
                    # "422: Currency not supported" without reading
                    # integration_call_logs directly — the caller only ever
                    # hears the generic/onError bridge above.
                    self.log_event(
                        "api_request_failed",
                        event_source="app",
                        severity="error",
                        details={
                            "node_id": _completed_api_node.id,
                            "node_name": _completed_api_node.data.get("name"),
                            "status_code": result.get("status_code"),
                            "error_type": result.get("error_type"),
                            "error_detail": result.get("error_detail") or result.get("message"),
                            "onerror_configured": bool(_api_config.get("onError")),
                        },
                    )
                if _completion_bridge and hasattr(params, "llm") and params.llm is not None:
                    try:
                        await params.llm.push_frame(TTSSpeakFrame(text=_completion_bridge))
                        self._capture_direct_speech(_completion_bridge)
                        logger.info(
                            f"🗣️ Spoke API completion bridge for {tool_name}: "
                            f"{'success' if result.get('success') else 'error'}"
                        )
                    except Exception as _bridge_err:
                        logger.warning(
                            f"Could not emit API completion bridge for {tool_name}: {_bridge_err}"
                        )

            # CRITICAL: Refresh the LLM's exposed tools whenever this call advanced
            # the flow position. Slot collection is not the only thing that advances
            # the flow — set_variable / api_request / router / confirmation /
            # save_record action nodes also move `current` forward WITHOUT returning
            # "collected". Since get_function_schemas() now gates action functions to
            # the reachable node, refreshing only on "collected" would strand the
            # call on a stale tool list (e.g. after a set_var advances to an api
            # node, execute_<api> would never be exposed and the call would hang).
            # Terminal actions (transfer/end) are handled below and return before
            # reaching the result_callback, so we skip the refresh for them.
            if (
                result.get("action") not in ("transfer", "end")
                and executor.state.current_node_id != _prev_node_id
            ):
                self.update_llm_tools_for_flow(tool_name)

            # A collection function result normally starts a second LLM
            # completion so the model can acknowledge the value and ask the
            # next question. On live calls that continuation is not guaranteed:
            # the tool call can complete with no spoken text, leaving the caller
            # in silence until they repeat themselves. Speak the next configured
            # collection prompt directly instead. The result still enters the
            # LLM context, so its tools and validation stay current for the next
            # caller turn.
            next_slot = result.get("next_slot") or {}
            next_prompt = str(next_slot.get("prompt") or "").strip()
            # Seed from _api_spoke_directly so that a directly-spoken API result
            # propagates run_llm=False without being overridden by the False
            # initialiser below.  Collection-prompt and speak_directly branches
            # below may still set this to True independently.
            _spoke_directly = _api_spoke_directly
            if result.get("collected") and next_prompt:
                await params.llm.push_frame(TTSSpeakFrame(text=next_prompt))
                self._capture_direct_speech(next_prompt)
                logger.info(
                    f"🗣️ Spoke next flow prompt for {tool_name}: "
                    f"{next_slot.get('variable')!r}"
                )
                _spoke_directly = True
            elif (
                not _completed_api_node
                and result.get("speak_directly")
                and result.get("action") not in ("transfer", "end")
            ):
                # Task #534 — CONFIRMATION, ROUTER, SET_VARIABLE, and
                # SAVE_RECORD results had no direct-speech guarantee at all:
                # the tool call could complete with nothing spoken, leaving
                # the caller in silence until they repeated themselves (the
                # exact failure seen on a live call after confirm_details).
                # FlowExecutor marks these results with speak_directly=True
                # whenever "message" (or the verbatim speak_exactly override)
                # is genuine caller-facing text, so speak it directly here
                # too — the same guarantee collection prompts already have.
                _direct_text = str(result.get("speak_exactly") or result.get("message") or "").strip()
                if _direct_text:
                    await params.llm.push_frame(TTSSpeakFrame(text=_direct_text))
                    self._capture_direct_speech(_direct_text)
                    logger.info(
                        f"🗣️ Spoke direct flow response for {tool_name} "
                        f"({function_name}): {_direct_text!r}"
                    )
                    _spoke_directly = True

            # Handle special actions
            if result.get("action") == "transfer":
                target = result.get("target")
                flow_transfer_mode = result.get("transfer_mode", "warm")
                # The announcement the LLM/flow speaks before the transfer —
                # used to scale degraded-path playback waits so long messages
                # are never clipped when the mark ack is missing.
                _flow_transfer_msg = result.get("message") or None
                import asyncio as _asyncio_flow
                import re as _re_flow

                if self.twilio_client and self.call_sid and target:

                    async def _execute_flow_transfer():
                        """Performs the Twilio REST call for a flow-triggered transfer.
                        Runs as an asyncio task after speech ends — outside Pipecat's
                        function-call timeout. Pushes EndFrame only after Twilio
                        accepts the transfer update.

                        Thread-safety contract:
                        - _save_call_transcript is awaited BEFORE any session opens.
                        - Recording stop is already off-loop via to_thread; kept outside the DB block.
                        - TwiML is built on the event loop — pure Python string ops, no I/O.
                        - ALL DB work (record_transfer, get_call_log, ACW query) and the blocking
                          Twilio calls().update() REST call run inside _db_flow_record_and_transfer,
                          which is called via asyncio.to_thread. The session is opened and closed
                          entirely within that function.
                        - self.twilio_client is the Twilio helper-library Client (uses requests
                          internally). It holds no event-loop references and is safe to call from
                          any thread — consistent with existing to_thread usage elsewhere.
                        - Only plain Python scalars cross the thread boundary (strings, bool).
                        - No ORM object leaves the thread.
                        """
                        _flow_transfer_succeeded = False
                        _flow_call_already_ended = False
                        try:
                            await self._await_twilio_playback_mark(
                                "flow-transfer", expected_speech_text=_flow_transfer_msg
                            )

                            # ── Step 1: Save transcript ──────────────────────────────────────────
                            # Must happen before any session opens — _save_call_transcript is async
                            # and opens/closes its own session internally.
                            if self.call_handler and hasattr(
                                self.call_handler, "_save_call_transcript"
                            ):
                                try:
                                    llm_context = self.call_handler.call_contexts.get(self.call_sid)
                                    await self.call_handler._save_call_transcript(
                                        self.call_sid, llm_context
                                    )
                                    logger.info(
                                        f"📝 Saved transcript before flow transfer for call {self.call_sid}"
                                    )
                                except Exception as _e:
                                    logger.error(
                                        f"Error saving transcript before flow transfer: {_e}"
                                    )

                            # ── Step 2: Stop recording ────────────────────────────────────────────
                            # Already off-loop via to_thread. Kept outside the DB block so no
                            # session is open across this await.
                            _flow_rec_sid = (
                                self.call_handler.call_recording_sids.get(self.call_sid)
                                if self.call_handler
                                else None
                            )
                            if _flow_rec_sid:
                                try:
                                    _frs_cap = _flow_rec_sid  # plain string
                                    _fcsid_cap = self.call_sid  # plain string
                                    _ftcl_cap = self.twilio_client  # thread-safe SDK client
                                    await _asyncio_flow.to_thread(
                                        lambda: (
                                            _ftcl_cap.calls(_fcsid_cap)
                                            .recordings(_frs_cap)
                                            .update(status="stopped")
                                        )
                                    )
                                    logger.info(
                                        f"🛑 Recording {_flow_rec_sid} stopped before flow transfer for call {self.call_sid}"
                                    )
                                    self.call_handler.call_recording_sids.pop(self.call_sid, None)
                                except Exception as _stop_err_flow:
                                    logger.warning(
                                        f"Failed to stop recording before flow transfer for call {self.call_sid}: {_stop_err_flow}"
                                    )

                            # ── Step 3: Build TwiML on event loop ────────────────────────────────
                            # Pure Python string operations — no DB, no network, no await.
                            # Do not include an explicit stream-stop verb: this call
                            # uses bidirectional Connect/Stream, which Twilio stops
                            # when the call is updated or the WebSocket closes.
                            twiml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]
                            if flow_transfer_mode == "cold":
                                digits_only = _re_flow.sub(r"[^\d+]", "", target)
                                sip_uri = f"sip:{digits_only}@pstn.twilio.com"
                                twiml_parts.append(f"<Refer><Sip>{sip_uri}</Sip></Refer>")
                                twiml_parts.append("</Response>")
                                logger.info(f"🔄 Cold SIP REFER flow transfer to {target}")
                            else:
                                # Warm transfer: replace the live call with <Dial>.
                                caller_id = self.to_number or os.environ.get(
                                    "TWILIO_PHONE_NUMBER", ""
                                )
                                if caller_id:
                                    twiml_parts.append(
                                        f'<Dial timeout="30" callerId="{caller_id}">'
                                    )
                                else:
                                    twiml_parts.append('<Dial timeout="30">')
                                base_url = get_public_base_url()
                                status_callback = f"{base_url}/api/calls/transfer-status"
                                twiml_parts.append(
                                    f'<Number statusCallback="{status_callback}" '
                                    f'statusCallbackEvent="initiated ringing answered completed">'
                                    f"{target}</Number>"
                                )
                                twiml_parts.append("</Dial>")
                                twiml_parts.append("</Response>")
                                logger.info(f"🔄 Warm flow transfer to {target}")

                            # ── Step 4: All DB + Twilio REST in one thread ───────────────────────
                            # Capture plain scalars before crossing the thread boundary.
                            # No ORM object and no session handle may cross this line.
                            _cap_call_sid = self.call_sid  # str
                            _cap_twilio = self.twilio_client  # thread-safe SDK client
                            _cap_twiml = "\n".join(twiml_parts)  # str
                            _cap_target = target  # str
                            _cap_mode = flow_transfer_mode  # str

                            def _db_flow_record_and_transfer():
                                from ..database import SessionLocal as _SL
                                from ..services.call_logger import CallLogger as _CL

                                _db = _SL()
                                try:
                                    _cl = _CL(_db)
                                    transfer_type = "cold" if _cap_mode == "cold" else "external"
                                    _cl.record_transfer(
                                        call_sid=_cap_call_sid,
                                        transfer_to=_cap_target,
                                        transfer_type=transfer_type,
                                    )
                                    # Blocking Twilio REST — safe here, we are in a thread
                                    _cap_twilio.calls(_cap_call_sid).update(twiml=_cap_twiml)
                                    logger.info(f"✅ Flow transfer to {_cap_target} initiated")

                                    # Trigger ACW for cold flow transfers — Twilio won't call /connect-complete
                                    if _cap_mode == "cold":
                                        try:
                                            from ..models import Assistant as _Assistant2
                                            from ..services.acw_service import (
                                                run_acw_background as _run_acw_bg2,
                                                should_auto_run_acw as _should_acw2,
                                            )

                                            _flow_call_log = _cl.get_call_log(_cap_call_sid)
                                            if _flow_call_log and _flow_call_log.assistant_id:
                                                _flow_asst = (
                                                    _db.query(_Assistant2)
                                                    .filter(
                                                        _Assistant2.id
                                                        == _flow_call_log.assistant_id
                                                    )
                                                    .first()
                                                )
                                                if _should_acw2(_flow_asst, _cap_call_sid):
                                                    import threading

                                                    # Extract scalar ID before ORM object goes out of scope
                                                    _acw_log_id = _flow_call_log.id
                                                    threading.Thread(
                                                        target=_run_acw_bg2,
                                                        args=(_acw_log_id,),
                                                        daemon=True,
                                                    ).start()
                                                    logger.info(
                                                        f"ACW background thread started for cold flow transfer call {_cap_call_sid}"
                                                    )
                                        except Exception as _acw_e2:
                                            logger.error(
                                                f"Failed to start ACW thread after cold flow transfer: {_acw_e2}"
                                            )
                                        # Trigger record auto-extraction too — Twilio
                                        # skips /connect-complete for REST <Refer> updates.
                                        try:
                                            from ..services.record_extraction_service import (
                                                has_active_extraction_types as _has_extract2,
                                                run_record_extraction_for_call_in_thread as _run_extract2,
                                            )

                                            _rec_flow_log = _cl.get_call_log(_cap_call_sid)
                                            if (
                                                _rec_flow_log
                                                and _rec_flow_log.account_id
                                                and _has_extract2(
                                                    _rec_flow_log.account_id,
                                                    _rec_flow_log.assistant_id,
                                                    _db,
                                                )
                                            ):
                                                import threading

                                                _rec_flow_log_id = _rec_flow_log.id
                                                threading.Thread(
                                                    target=_run_extract2,
                                                    args=(_rec_flow_log_id,),
                                                    daemon=True,
                                                ).start()
                                                logger.info(
                                                    f"Record extraction thread started for cold flow transfer call {_cap_call_sid}"
                                                )
                                        except Exception as _rec_e2:
                                            logger.error(
                                                f"Failed to start record extraction thread after cold flow transfer: {_rec_e2}"
                                            )
                                finally:
                                    _db.close()
                                return True

                            _flow_transfer_succeeded = await _asyncio_flow.to_thread(
                                _db_flow_record_and_transfer
                            )

                        except Exception as e:
                            if isinstance(e, _TwilioRestException) and e.status == 400:
                                logger.warning(
                                    f"⚠️ Twilio 400 on flow transfer REST call for {self.call_sid} — "
                                    "call leg already ended; treating as clean end"
                                )
                                _flow_call_already_ended = True
                            else:
                                logger.error(f"Flow transfer failed: {e}")
                        finally:
                            if _flow_transfer_succeeded or _flow_call_already_ended:
                                await params.llm.push_frame(EndFrame())
                            else:
                                logger.warning(
                                    f"Flow transfer did not succeed for {self.call_sid} — "
                                    "EndFrame not pushed; pipeline remains active"
                                )

                    # Bind the transfer to the LLM's current audio context (reset=False
                    # reads _turn_context_id from the TTS service).  Falls back to
                    # BotStopped watcher then fixed delay — never reset=True because the
                    # speech was initiated upstream by the LLM, not by this handler.
                    self._run_after_speech(
                        _execute_flow_transfer,
                        label="Flow transfer",
                        reset=False,
                        speech_text=_flow_transfer_msg,
                    )
                else:
                    # No Twilio client / call_sid / target — end the pipeline immediately
                    await params.llm.push_frame(EndFrame())
                # Return immediately — do NOT call result_callback for transfer actions.
                # Calling it would trigger a new LLM generation cycle, which cancels
                # any in-flight TTS context before Deepgram audio arrives, preventing
                # BotStoppedSpeakingFrame from firing and killing the transfer callback.
                return

            elif result.get("action") == "end":
                end_msg = result.get("message", "Goodbye!")

                # Same decoupled pattern as end_call_handler: register the
                # hangup as a post-speech callback, push the goodbye, return.
                # _finalize_call_end awaits the Twilio playback mark before the
                # REST hangup so the full message is heard.  Previously the
                # REST hangup fired immediately after pushing the TTSSpeakFrame,
                # clipping the flow END message.
                async def _finalize_flow_end():
                    await self._finalize_call_end(
                        params.llm, "flow_end", speech_text=end_msg
                    )

                # Bind to the LLM's current audio context (reset=False reads
                # _turn_context_id from the TTS service) — speech was initiated
                # upstream by the LLM so we must not reset the watcher.
                self._run_after_speech(
                    _finalize_flow_end, label="Flow END", reset=False, speech_text=end_msg
                )

                await params.llm.push_frame(TTSSpeakFrame(end_msg))
                # Do NOT call result_callback — same reasoning as the transfer
                # branch above (a new LLM cycle would cancel in-flight TTS).
                return

            # Add current progress to result for LLM context (non-terminal actions only)
            result["progress"] = executor.get_progress()

            # Clean the result for the LLM — remove raw API response blobs that
            # add noise, promote voice_result → result, but preserve all control
            # fields (speak_exactly, next_slot, out_of_order, etc.) that
            # slot-collection handlers set and the LLM needs to read.
            for _blob_key in (
                "response",
                "data",
                "extracted_variables",
                "response_instructions",
                "voice_result_is_auto_summary",
            ):
                result.pop(_blob_key, None)
            if "voice_result" in result:
                result["result"] = result.pop("voice_result")
            elif "result" not in result:
                result["result"] = result.get("message", "Done")
            if _spoke_directly:
                await params.result_callback(
                    result,
                    properties=FunctionCallResultProperties(run_llm=False),
                )
            else:
                await params.result_callback(result)

        return handler

    def _create_flow_trigger_handler(self, tool_name: str):
        """Create handler for starting a flow.

        Uses tool_name to look up the stored executor.
        """

        async def handler(params: FunctionCallParams):
            logger.info(f"🎬 Starting flow: {tool_name}")

            executor = self._flow_executors.get(tool_name)
            if not executor:
                logger.error(f"No executor found for flow {tool_name}")
                await params.result_callback({"status": "error", "message": "Flow not initialized"})
                return

            # Reject retries for this same flow before they can replay its
            # greeting, re-import values, or record duplicate tool usage.
            if self._flow_has_started(executor):
                logger.warning(
                    f"🚫 Rejecting duplicate start_{tool_name}: flow is already "
                    f"in progress (node={executor.state.current_node_id!r}) for this call"
                )
                await params.result_callback(
                    {
                        "success": False,
                        "message": (
                            "This request is already in progress on this call — "
                            "finish or resolve it first."
                        ),
                    }
                )
                return

            # Flow-switch race guard (Task #534, defense-in-depth). Both
            # flow triggers are exposed together only in the very first
            # completion, before either flow has advanced — disabling
            # parallel_tool_calls (engine.py) closes the main way a single
            # LLM turn could fire two of them at once, but this is a second,
            # independent line of defense against a start_<other_flow> call
            # landing while THIS flow is already under way (a stray/retried
            # turn, a provider that ignores parallel_tool_calls, etc). This
            # is exactly what produced a phantom "Housekeeping Request"
            # flow_sessions row mid-call with no transcript trace on a real
            # call. Reject the second trigger instead of silently starting a
            # second, unrelated flow session in parallel.
            for _other_name, _other_executor in self._flow_executors.items():
                if _other_name == tool_name:
                    continue
                if (
                    _other_executor.state.current_node_id
                    and _other_executor.state.current_node_id
                    != _other_executor.flow_config.initial_node
                    and not _other_executor.state.is_complete
                ):
                    logger.warning(
                        f"🚫 Rejecting start_{tool_name}: flow {_other_name!r} is "
                        f"already in progress (node="
                        f"{_other_executor.state.current_node_id!r}) for this call"
                    )
                    await params.result_callback(
                        {
                            "success": False,
                            "message": (
                                "Another request is already in progress on this "
                                "call — finish or resolve that first."
                            ),
                        }
                    )
                    return

            # Track flow usage in call logs (executor holds the tool UUID)
            self.track_tool_usage(
                tool_name,
                is_flow=True,
                flow_id=getattr(executor, "flow_tool_id", None),
            )

            imported = executor.import_caller_slots(dict(params.arguments or {}))
            if not imported["success"]:
                await params.result_callback(
                    {
                        "status": "invalid_arguments",
                        "message": "Some provided details were invalid.",
                        "errors": imported["errors"],
                    }
                )
                return

            # get_initial_messages() always enters the flow's first graph node.
            # With waitForResponse=true it returns only the configured greeting;
            # with false it also returns the downstream auto-walk messages.
            # Speak every returned message directly so the LLM does not replay
            # the flow greeting while the correct next tools are being exposed.
            initial_messages = executor.get_initial_messages()
            executor.advance_past_satisfied_collects()
            # The start handler bypasses handle_function_call(), so persist
            # progress explicitly. This is best-effort like all live-flow
            # snapshots: a write failure must not drop an active caller.
            await executor._snapshot_state()
            spoke_any = False
            for message in initial_messages:
                if message:
                    await params.llm.push_frame(TTSSpeakFrame(message))
                    self._capture_direct_speech(message)
                    spoke_any = True

            # State is now at the first unsatisfied collect node or the next
            # mandatory action gate. Updating tools exposes only that valid
            # next function and removes the stale start trigger.
            self.update_llm_tools_for_flow(tool_name)

            # Give the LLM the remaining variable list for context so it knows
            # what to collect, but omit the greeting — it has already been spoken.
            # Each entry carries its collect node's typed instructions so the
            # LLM knows HOW to ask/handle every value, not just what to collect.
            variables_to_collect = []
            for v in executor.flow_config.variables:
                if v.key in executor.state.collected_slots:
                    continue
                entry = {"key": v.key, "type": v.type.value, "description": v.description}
                try:
                    raw_instructions = executor._get_instructions_for_variable(v.key)
                except Exception:  # noqa: BLE001 - guidance is best-effort
                    raw_instructions = None
                if raw_instructions and raw_instructions.strip():
                    entry["instructions"] = substitute_variables(
                        raw_instructions.strip(), executor.state.collected_slots
                    )
                variables_to_collect.append(entry)

            progress = executor.get_progress()

            result_payload = {
                "status": "flow_started",
                "progress": progress,
                "variables_to_collect": variables_to_collect,
                "instructions": (
                    "The configured initial messages have already been spoken "
                    "to the caller. Do NOT greet again or repeat any of those "
                    "messages — wait for the caller's response. Then collect the "
                    "required information by calling the collect_* functions as you "
                    "gather each value, asking for each piece naturally in "
                    "conversation."
                ),
            }

            # Same CURRENT NODE guidance the simulator injects per turn. If a
            # prompt was included in the initial messages, frame it as
            # reference-only to avoid a duplicate question on the caller's
            # first answer.
            try:
                node_context = executor.get_current_node_context()
            except Exception:  # noqa: BLE001 - guidance is best-effort
                node_context = None
            if node_context:
                result_payload["current_node_context"] = (
                    "NOTE: the prompt below has ALREADY been spoken to the caller "
                    "— do not repeat it; use it only to interpret their answer:\n"
                    + node_context
                )

            # The greeting + first question were just spoken via TTSSpeakFrame,
            # so suppress the post-function-call LLM completion. Without this
            # the LLM immediately generates its own greeting/question on top of
            # the spoken one — the "double greeting" the caller hears at flow
            # start. The result still lands in context, so when the caller
            # answers, the next completion sees the flow state and guidance.
            # If nothing was actually spoken (misconfigured flow with no
            # initial messages), keep the default completion so the caller
            # never gets dead air.
            if spoke_any:
                await params.result_callback(
                    result_payload,
                    properties=FunctionCallResultProperties(run_llm=False),
                )
            else:
                logger.warning(
                    f"Flow {tool_name} produced no initial messages at trigger; "
                    "keeping the post-function LLM completion to avoid dead air."
                )
                await params.result_callback(result_payload)

        return handler


# Helper function to load tools for a voice agent
def load_tools_for_assistant(
    assistant_id: str, db_session
) -> List[tuple[Dict[str, Any], Callable]]:
    """Load all active tools for an assistant and convert to Pipecat functions.

    Usage:
        # In voice agent initialization
        from botelier.voice.function_mapper import load_tools_for_assistant

        tools = load_tools_for_assistant("assistant-123", db)
        mapper = FunctionMapper()

        for tool in tools:
            schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(schema['name'], handler)

    Args:
        assistant_id: Assistant ID to load tools for
        db_session: SQLAlchemy database session

    Returns:
        List of (function_schema, handler) tuples ready for LLM registration
    """
    from botelier.models.tool import Tool

    # Query active tools
    tools = (
        db_session.query(Tool)
        .filter(Tool.assistant_id == assistant_id, Tool.is_active == "true")
        .all()
    )

    # Convert to Pipecat functions
    mapper = FunctionMapper()
    return [mapper.map_tool_to_function(tool) for tool in tools]

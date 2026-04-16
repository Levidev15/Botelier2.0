"""
Botelier Voice Engine Implementation

This module contains the actual implementation that uses Pipecat.
This is an internal module - hotel developers don't interact with this directly.

Key Design Principle:
- Uses Pipecat's proper InputParams classes for type safety
- Maps database configuration to Pipecat's expected parameters
- Supports provider-specific features (Flux STT, prompt caching, etc.)
"""

import asyncio
import os
import time
from typing import Optional, Dict, Any, Callable
from loguru import logger

# Lazy imports for provider services to avoid startup issues with optional dependencies
# Services will be imported only when actually used
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.transcriptions.language import Language
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    AudioRawFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
)
from pipecat.processors.user_idle_processor import UserIdleProcessor
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_mute.function_call_user_mute_strategy import FunctionCallUserMuteStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy

from .agent import VoiceAgentConfig
from ..config.providers import is_flux_model


class InterruptionTracker(FrameProcessor):
    """
    Tracks TTS content being spoken and detects when it's interrupted.
    
    Placed before TTS in the pipeline to monitor text frames.
    When an InterruptionFrame is detected, calls the callback with the
    content that was interrupted.
    """
    
    def __init__(self, on_interruption: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(**kwargs)
        self._current_text = ""
        self._on_interruption = on_interruption
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Track outgoing TTS content (text frames from LLM)
        if isinstance(frame, (TextFrame, TTSSpeakFrame)):
            if hasattr(frame, 'text') and frame.text:
                self._current_text = frame.text
                logger.debug(f"🎤 Tracking TTS: {frame.text[:50]}...")
        
        # Detect interruption
        if isinstance(frame, InterruptionFrame):
            if self._current_text and self._on_interruption:
                logger.info(f"🛑 Interruption detected for: {self._current_text[:50]}...")
                self._on_interruption(self._current_text)
            self._current_text = ""  # Reset after interruption
        
        # CRITICAL: Always push frames through to next processor
        await self.push_frame(frame, direction)


class LLMResponseCapture(FrameProcessor):
    """
    Pure-observer processor that captures each complete LLM response.

    Placed immediately after the LLM in the pipeline so it sees LLM output
    frames before they reach the TTS service.  ALL frames are passed through
    unmodified — this processor never drops or delays any frame.

    When a complete response is assembled (LLMFullResponseEndFrame received),
    ``on_llm_response(text, timestamp)`` is called.  The handler stores the
    response in a per-call buffer that is consulted at transcript-save time to
    recover responses that the LLM context never committed (caller hung up
    mid-generation).

    Uses a TextFrame check (superclass of LLMTextFrame) gated by _in_response so
    it works across all LLM providers that may emit generic TextFrame tokens.
    """

    def __init__(self, on_llm_response=None, on_llm_start=None, call_start_mono: float = 0.0, timing_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self._buffer: str = ""
        self._in_response: bool = False
        self._on_llm_response = on_llm_response
        self._on_llm_start = on_llm_start
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._llm_turn_start_mono: float = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._in_response = True
            self._llm_turn_start_mono = time.monotonic()
            self._timing_state["t_llm_start"] = self._llm_turn_start_mono
            _elapsed_ms = (self._llm_turn_start_mono - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            _t_stt = self._timing_state.get("t_stt", 0.0)
            _stt_to_llm_ms = (self._llm_turn_start_mono - _t_stt) * 1000 if _t_stt else 0.0
            logger.debug(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] LLM first token received | "
                f"STT→LLM: {_stt_to_llm_ms:.0f}ms"
            )
            if self._on_llm_start:
                try:
                    self._on_llm_start()
                except Exception:
                    logger.exception("LLMResponseCapture: error in on_llm_start callback")

        elif isinstance(frame, TextFrame) and self._in_response:
            if frame.text:
                self._buffer += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._in_response = False
            text = self._buffer.strip()
            self._buffer = ""
            _now_mono = time.monotonic()
            self._timing_state["t_llm_end"] = _now_mono
            _elapsed_ms = (_now_mono - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            _gen_ms = (_now_mono - self._llm_turn_start_mono) * 1000 if self._llm_turn_start_mono else 0.0
            logger.debug(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] LLM response complete: "
                f"{len(text)} chars, generation={_gen_ms:.0f}ms"
            )
            if text and self._on_llm_response:
                try:
                    from datetime import datetime as _dt
                    self._on_llm_response(text, _dt.utcnow())
                except Exception:
                    logger.exception("LLMResponseCapture: error in on_llm_response callback")

        await self.push_frame(frame, direction)


class UserTurnCapture(FrameProcessor):
    """
    Pure-observer processor that captures each finalized user utterance with a
    wall-clock timestamp.

    Placed immediately after the STT mute filter and before the LLM context
    aggregator so it sees only the TranscriptionFrames that will be committed
    to the LLM context (i.e. post-muting).  ALL frames pass through unmodified.

    Calls ``on_user_turn(text, timestamp)`` for each non-empty transcription so
    that ``_extract_transcript`` can annotate user messages with the actual time
    they were finalized rather than the generic save-time stamp.

    Also emits a ``turn_finalized`` CallEvent per finalized transcription when
    an ``event_queue`` is wired (via ``set_event_queue``).  This is the true
    per-turn denominator — fires whether or not the pipeline then successfully
    responds.  Maintains a monotonic 1-based ``turn_index`` that is also written
    into ``timing_state["turn_index"]`` so the matching ``turn_latency`` event
    (emitted downstream by ``TtsPipelineLatencyTracker``) can reference it.
    """

    def __init__(self, on_user_turn=None, call_start_mono: float = 0.0, timing_state: dict = None, event_queue=None, **kwargs):
        super().__init__(**kwargs)
        self._on_user_turn = on_user_turn
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._event_queue = event_queue
        self._turn_index = 0

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text and frame.text.strip():
            _t_stt = time.monotonic()
            self._timing_state["t_stt"] = _t_stt
            self._turn_index += 1
            self._timing_state["turn_index"] = self._turn_index
            _elapsed_ms = (_t_stt - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            _t_last_inbound = self._timing_state.get("t_last_inbound", 0.0)
            _inbound_to_stt_ms = (_t_stt - _t_last_inbound) * 1000 if _t_last_inbound else 0.0
            _transcript = frame.text.strip()
            logger.debug(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] STT transcript finalized: "
                f'"{_transcript[:60]}" | '
                f"inbound→STT: {_inbound_to_stt_ms:.0f}ms"
            )
            if self._event_queue is not None:
                self._event_queue.log(
                    "turn_finalized",
                    event_source="pipecat",
                    severity="info",
                    details={
                        "turn_index": self._turn_index,
                        "inbound_to_stt_ms": int(_inbound_to_stt_ms),
                        "transcript_chars": len(_transcript),
                    },
                )
            if self._on_user_turn:
                try:
                    from datetime import datetime as _dt
                    self._on_user_turn(_transcript, _dt.utcnow())
                except Exception:
                    logger.exception("UserTurnCapture: error in on_user_turn callback")

        await self.push_frame(frame, direction)


class FirstUserSpeechTracker(FrameProcessor):
    """
    Detects the first non-empty transcription from the user and logs a
    user_first_speech event via the injected CallEventQueue.

    Placed between the STT service and the context_aggregator so it
    intercepts TranscriptionFrames on the way downstream.
    Only the very first non-empty transcript is reported — subsequent turns
    are intentionally ignored (per spec: no recurring speech events).
    """

    def __init__(self, event_queue=None, **kwargs):
        super().__init__(**kwargs)
        self._event_queue = event_queue
        self._logged = False

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if (
            not self._logged
            and isinstance(frame, TranscriptionFrame)
            and hasattr(frame, "text")
            and frame.text
            and frame.text.strip()
        ):
            self._logged = True
            if self._event_queue is not None:
                self._event_queue.log(
                    "user_first_speech",
                    event_source="pipecat",
                    severity="info",
                    details={"transcript": frame.text.strip()[:200]},
                )
            logger.debug(f"user_first_speech logged: {frame.text.strip()[:50]}...")

        await self.push_frame(frame, direction)


class IdleTimeoutTracker:
    """
    Thin wrapper that builds a UserIdleProcessor whose callback logs an
    idle_timeout event via an injected CallEventQueue.

    Usage::
        tracker = IdleTimeoutTracker(timeout=30.0)
        pipeline = Pipeline([..., tracker.processor, ...])
        # after pipeline creation:
        tracker.set_event_queue(event_queue)
    """

    def __init__(self, timeout: float = 30.0):
        self._event_queue = None
        self._retry_count = 0
        self.processor = UserIdleProcessor(
            callback=self._on_idle,
            timeout=timeout,
        )

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    async def _on_idle(self, processor: UserIdleProcessor, retry_count: int) -> bool:
        """Called each time the idle timeout fires.  Returns False to stop retrying.

        Note: there is no explicit stop-event guard here against a race with
        pipeline teardown.  That guard lives in CallEventQueue.log() itself —
        it checks _stop_event.is_set() and silently drops any event enqueued
        after flush_and_stop() is called.  This single centralised guard
        protects all callers, including this one.
        """
        if self._event_queue is not None:
            self._event_queue.log(
                "idle_timeout",
                event_source="pipecat",
                severity="warning",
                details={"retry_count": retry_count, "timeout_secs": processor._timeout},
            )
            # Boundary event: makes "the caller went silent" explicitly visible
            # in the dashboard timeline alongside the existing idle_timeout
            # observability event (Task #94).
            self._event_queue.log(
                "caller_silence_detected",
                event_source="pipecat",
                severity="info",
                details={"retry_count": retry_count, "timeout_secs": processor._timeout},
            )
        logger.info(f"idle_timeout / caller_silence_detected logged (retry #{retry_count})")
        return False  # One notification per idle period; let pipeline decide to hang up elsewhere


class GreetingCompletionTracker(FrameProcessor):
    """
    Logs a greeting_completed event when the greeting TTS finishes speaking.

    Placed immediately after the TTS service so it sees BotStoppedSpeakingFrame
    as it flows downstream.  Only the very first BotStoppedSpeakingFrame is
    reported — subsequent ones (regular turn-taking) are ignored.

    WebSocket liveness guard: if ``is_call_active`` is wired (via
    ``set_call_active``), the callback and event are suppressed when the
    WebSocket is already closed.  This prevents buffered TTS frames that drain
    after a hangup from incorrectly marking the greeting as completed — the
    caller never heard those frames.
    """

    def __init__(self, event_queue=None, is_call_active=None, **kwargs):
        super().__init__(**kwargs)
        self._event_queue = event_queue
        self._greeting_callback = None
        self._logged = False
        self._is_call_active = is_call_active  # Optional[Callable[[], bool]]

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def set_greeting_callback(self, callback) -> None:
        """Set an async callback invoked once when the greeting finishes playing."""
        self._greeting_callback = callback

    def set_call_active(self, is_call_active) -> None:
        """
        Wire a callable that returns True when the WebSocket is still connected.

        If the callable returns False when BotStoppedSpeakingFrame arrives, the
        greeting callback is suppressed — the audio drained after the caller hung
        up and was never delivered.
        """
        self._is_call_active = is_call_active

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not self._logged and isinstance(frame, BotStoppedSpeakingFrame):
            self._logged = True

            # Guard: if the WebSocket is already closed the TTS frames are
            # draining from an internal buffer after the caller hung up.
            # Do NOT mark the greeting as completed — the caller never heard it.
            if self._is_call_active is not None and not self._is_call_active():
                logger.info(
                    "GreetingCompletionTracker: WebSocket closed before "
                    "BotStoppedSpeakingFrame — caller hung up mid-greeting, "
                    "suppressing greeting_completed callback"
                )
                await self.push_frame(frame, direction)
                return

            if self._event_queue is not None:
                self._event_queue.log(
                    "greeting_completed",
                    event_source="pipecat",
                    severity="info",
                )
            if self._greeting_callback is not None:
                try:
                    await self._greeting_callback()
                except Exception as _cb_err:
                    logger.error(f"greeting_callback error: {_cb_err}")
            logger.debug("greeting_completed logged")

        await self.push_frame(frame, direction)


class TtsCompletionWatcher(FrameProcessor):
    """
    Watches for BotStoppedSpeakingFrame to signal TTS completion.

    Placed in the pipeline immediately after the TTS service so it can observe
    BotStoppedSpeakingFrame as it flows downstream toward the transport output.

    Two usage modes:

    1. Callback (preferred for transfers) — decouples the action from the
       Pipecat function-call timeout:

        watcher.reset()
        watcher.schedule_after_speech(my_async_callback)
        await llm.push_frame(TTSSpeakFrame(message))
        # return immediately — callback fires when speech ends

    2. Await (legacy, blocks the function handler — subject to Pipecat timeout):

        watcher.reset()
        await llm.push_frame(TTSSpeakFrame(message))
        await watcher.wait_until_done(timeout=15.0)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._speaking_done = asyncio.Event()
        self._speaking_done.set()  # Start in "done" state — no pending speech
        self._on_done_callback = None  # One-shot async callback

    def reset(self):
        """
        Clear the completion event.

        Call this synchronously (no await) just before pushing a TTSSpeakFrame
        so that schedule_after_speech / wait_until_done captures the correct
        BotStoppedSpeakingFrame.
        """
        self._speaking_done.clear()

    def schedule_after_speech(self, callback, timeout: float = 5.0) -> None:
        """
        Run ``callback`` as soon as the current speech is done.

        - If speech has already ended (event is set), fires callback immediately
          via asyncio.create_task so it runs outside the current stack frame.
        - If speech is still in progress, registers it as a one-shot callback
          that fires when the next BotStoppedSpeakingFrame arrives.

        A safety ``timeout`` (default 5 s) guarantees the callback fires even
        when BotStoppedSpeakingFrame never arrives — for example when Pipecat's
        FunctionCallInProgressFrame wipes the TTS context before Deepgram audio
        returns, leaving the pipeline silent and the event permanently unset.

        This is the preferred method for transfer handlers: call reset() first,
        then schedule_after_speech(), then push the TTSSpeakFrame, then return
        immediately to Pipecat. The callback executes after speech completes
        regardless of how long TTS takes — entirely outside Pipecat's function-
        call timeout window.

        For flow transfers where speech was initiated upstream (no reset()),
        call schedule_after_speech() without reset(). If speech is already
        done the callback fires immediately; otherwise it waits.

        Args:
            callback: Async callable (no arguments) to invoke after speech ends.
            timeout:  Seconds to wait for BotStoppedSpeakingFrame before firing
                      the callback unconditionally.  Default 5 s.
        """
        if self._speaking_done.is_set():
            asyncio.create_task(callback())
        else:
            if self._on_done_callback is not None:
                logger.warning("TtsCompletionWatcher: overwriting existing on-done callback")
            self._on_done_callback = callback

            async def _timeout_guard():
                try:
                    await asyncio.wait_for(self._speaking_done.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    # BotStoppedSpeakingFrame never arrived within the window.
                    # Fire the callback now so the transfer is never permanently lost.
                    # Check atomically: process_frame may have already fired it.
                    cb = self._on_done_callback
                    self._on_done_callback = None
                    if cb is not None:
                        logger.warning(
                            f"TtsCompletionWatcher: BotStoppedSpeakingFrame did not arrive "
                            f"within {timeout}s — firing transfer callback via timeout"
                        )
                        try:
                            await cb()
                        except Exception:
                            logger.exception(
                                "TtsCompletionWatcher: unhandled exception in timeout callback"
                            )

            asyncio.create_task(_timeout_guard())

    def clear_callback(self) -> None:
        """
        Remove any pending one-shot callback.

        Call this on pipeline shutdown or call hang-up to avoid firing a
        stale transfer after the call has already ended.
        """
        self._on_done_callback = None

    async def wait_until_done(self, timeout: float = 15.0) -> bool:
        """
        Wait until BotStoppedSpeakingFrame is observed or the timeout expires.

        Returns:
            True  — speech completed within the timeout.
            False — timed out; caller should proceed with the transfer anyway.
        """
        try:
            await asyncio.wait_for(self._speaking_done.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"TtsCompletionWatcher: timed out after {timeout}s waiting for BotStoppedSpeakingFrame")
            return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStoppedSpeakingFrame):
            logger.debug("TtsCompletionWatcher: BotStoppedSpeakingFrame received — signalling done")
            self._speaking_done.set()
            # Fire and clear the one-shot callback if one is registered.
            # Use create_task so the callback runs outside this frame-processing
            # stack, avoiding any re-entrant pipeline issues.
            cb = self._on_done_callback
            self._on_done_callback = None
            if cb is not None:
                async def _guarded_cb(callback=cb):
                    try:
                        await callback()
                    except Exception:
                        logger.exception("TtsCompletionWatcher: unhandled exception in post-speech callback")
                asyncio.create_task(_guarded_cb())
        # Always pass frames through unchanged
        await self.push_frame(frame, direction)


class InboundAudioTracker(FrameProcessor):
    """
    Pure-observer placed immediately after ``transport.input()`` in the pipeline.

    Stamps ``timing_state["t_last_inbound"]`` with a monotonic clock on every
    inbound AudioRawFrame.  UserTurnCapture reads this to compute:

        Twilio inbound audio → STT transcript finalized  (inbound→STT delta)

    The delta captures total STT processing latency: the time from when the last
    audio chunk was delivered to the pipeline until Deepgram returned the final
    transcript.  Typical range for short utterances: 100–600 ms.
    """

    def __init__(self, timing_state: dict = None, **kwargs):
        super().__init__(**kwargs)
        self._timing_state = timing_state if timing_state is not None else {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame):
            self._timing_state["t_last_inbound"] = time.monotonic()
        await self.push_frame(frame, direction)


class TtsPipelineLatencyTracker(FrameProcessor):
    """
    Measures two pipeline-stage handoffs:

      3. LLM last token → TTS first audio chunk
         Streaming TTS often starts before LLM finishes; the delta may be
         negative (audio leading LLM end) — that is expected and informative.
         Logged when LLMFullResponseEndFrame arrives if first audio is already seen,
         or when first audio arrives if LLM already ended.

      4. TTS first audio chunk dispatched to transport
         Logged as a call-relative timestamp (T+Xms) on the first AudioRawFrame
         after an LLM response starts, capturing the moment audio hits transport.output().

    Place this processor immediately before ``transport.output()`` so it sees
    both the control frames from the LLM and the AudioRawFrames from TTS.

    The shared ``timing_state`` dict (passed by reference) is the only coupling
    between this processor and LLMResponseCapture / UserTurnCapture.
    """

    def __init__(self, call_start_mono: float = 0.0, timing_state: dict = None, event_queue=None, **kwargs):
        super().__init__(**kwargs)
        self._call_start_mono = call_start_mono
        self._timing_state = timing_state if timing_state is not None else {}
        self._event_queue = event_queue
        self._expecting_audio: bool = False
        self._t_first_audio: float = 0.0
        self._turn_emitted: bool = False  # Guards against double-emission per turn

    def set_event_queue(self, event_queue) -> None:
        self._event_queue = event_queue

    def _emit_turn_latency(self, t_llm_end: float) -> None:
        """Log LLM→TTS delta and emit the ``turn_latency`` CallEvent.

        Called exactly once per responded turn: whichever of LLMFullResponseEndFrame
        / first AudioRawFrame arrives second triggers this (both timestamps are
        required to compute the delta).  The ``_turn_emitted`` flag prevents a
        second emission if both branches end up calling this within the same turn.
        """
        if self._turn_emitted:
            return
        self._turn_emitted = True
        _t_first_audio_local = self._t_first_audio
        # Immediately clear per-turn state after capturing locally, so any stray
        # frames arriving before the next LLMFullResponseStartFrame cannot
        # re-trigger emission paths using stale values.
        self._t_first_audio = 0.0
        self._expecting_audio = False

        _delta_ms = (_t_first_audio_local - t_llm_end) * 1000
        _sign = "" if _delta_ms >= 0 else ""
        logger.debug(
            f"⏱️ LLM last token → TTS first audio: {_sign}{_delta_ms:.0f}ms "
            f"({'TTS led LLM end — streaming' if _delta_ms < 0 else 'TTS trailed LLM end'})"
        )

        if self._event_queue is None:
            return

        _t_stt = self._timing_state.get("t_stt", 0.0)
        _t_llm_start = self._timing_state.get("t_llm_start", 0.0)
        _t_last_inbound = self._timing_state.get("t_last_inbound", 0.0)
        _turn_index = self._timing_state.get("turn_index", 0)

        _inbound_to_stt_ms = int((_t_stt - _t_last_inbound) * 1000) if (_t_stt and _t_last_inbound) else 0
        _stt_to_llm_start_ms = int((_t_llm_start - _t_stt) * 1000) if (_t_llm_start and _t_stt) else 0
        _llm_generation_ms = int((t_llm_end - _t_llm_start) * 1000) if _t_llm_start else 0
        _llm_to_tts_first_audio_ms = int(_delta_ms)
        _turn_started_ms = int((_t_last_inbound - self._call_start_mono) * 1000) if (_t_last_inbound and self._call_start_mono) else 0
        _turn_responded_ms = int((_t_first_audio_local - self._call_start_mono) * 1000) if self._call_start_mono else 0

        self._event_queue.log(
            "turn_latency",
            event_source="pipecat",
            severity="info",
            details={
                "turn_index": _turn_index,
                "inbound_to_stt_ms": _inbound_to_stt_ms,
                "stt_to_llm_start_ms": _stt_to_llm_start_ms,
                "llm_generation_ms": _llm_generation_ms,
                "llm_to_tts_first_audio_ms": _llm_to_tts_first_audio_ms,
                "turn_started_ms": _turn_started_ms,
                "turn_responded_ms": _turn_responded_ms,
            },
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._expecting_audio = True
            self._t_first_audio = 0.0
            self._turn_emitted = False  # Reset per-turn emission guard
            # Per-turn isolation: clear the previous turn's LLM-end timestamp so
            # the first-audio branch below cannot read a stale value if this
            # turn's TTS audio begins before LLMFullResponseEndFrame arrives
            # (common in streaming TTS).  LLMResponseCapture will refresh this
            # key when it sees this turn's LLMFullResponseEndFrame.
            self._timing_state.pop("t_llm_end", None)

        elif self._expecting_audio and isinstance(frame, AudioRawFrame):
            self._expecting_audio = False
            self._t_first_audio = time.monotonic()
            _elapsed_ms = (self._t_first_audio - self._call_start_mono) * 1000 if self._call_start_mono else 0.0
            logger.debug(
                f"⏱️ [T+{_elapsed_ms:.0f}ms] TTS first audio chunk dispatched to transport"
            )
            # If LLM already ended (t_llm_end set), emit immediately.
            # Otherwise emission fires when LLMFullResponseEndFrame arrives below.
            _t_llm_end = self._timing_state.get("t_llm_end", 0.0)
            if _t_llm_end:
                self._emit_turn_latency(_t_llm_end)

        elif isinstance(frame, LLMFullResponseEndFrame) and self._t_first_audio:
            # LLM just finished; first audio already arrived (streaming overlap).
            _t_llm_end = self._timing_state.get("t_llm_end", 0.0)
            if _t_llm_end:
                self._emit_turn_latency(_t_llm_end)

        await self.push_frame(frame, direction)


# Fallback allowlist used only if providers.py cannot be imported at runtime.
# Keep in sync with STT_PROVIDERS[STTProvider.DEEPGRAM].available_models.
_DEEPGRAM_VALID_MODELS_FALLBACK: frozenset = frozenset([
    "nova-3-general",
    "nova-3-meeting",
    "nova-3-voicemail",
    "nova-3-finance",
    "nova-3-medical",
    "nova-2-general",
    "nova-2-meeting",
    "nova-2-phonecall",
    "nova-2-voicemail",
])


def _get_deepgram_valid_models() -> frozenset:
    """Return the canonical Deepgram model allowlist from providers.py.

    Reads the live ``available_models`` list so changes to providers.py are
    reflected without modifying engine.py.  Falls back to the static list
    above only if the import fails, which should never happen in production.
    """
    from ..config.providers import STT_PROVIDERS, STTProvider
    cfg = STT_PROVIDERS.get(STTProvider.DEEPGRAM)
    if cfg and cfg.available_models:
        return frozenset(cfg.available_models)
    return _DEEPGRAM_VALID_MODELS_FALLBACK


class BotelierDeepgramSTTService:
    """
    Mixin for DeepgramSTTService that aborts the retry loop on permanent
    HTTP errors (400, 401, 403) instead of retrying forever.

    Pipecat's ``_connection_handler`` catches every non-CancelledError
    exception and loops unconditionally.  When Deepgram rejects a model
    name with HTTP 400, this creates an infinite zombie loop that only a
    server restart can clear.  This mixin overrides ``_connection_handler``
    to detect 4xx status codes in the exception message and break the loop,
    logging an actionable ERROR instead.

    Use via multiple inheritance so MRO resolves this override first:
        class _Impl(BotelierDeepgramSTTService, DeepgramSTTService): pass
    """

    async def _connection_handler(self):
        from deepgram.core.events import EventType

        while True:
            connect_kwargs = self._build_connect_kwargs()
            try:
                async with self._client.listen.v1.connect(**connect_kwargs) as connection:
                    self._connection = connection
                    connection.on(EventType.MESSAGE, self._on_message)
                    connection.on(EventType.ERROR, self._on_error)
                    logger.debug(f"{self}: Websocket connection initialized")
                    keepalive_task = self.create_task(
                        self._keepalive_handler(), f"{self}::keepalive"
                    )
                    try:
                        await connection.start_listening()
                    finally:
                        await self.cancel_task(keepalive_task)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err_str = str(e)
                # Detect permanent HTTP errors — abort rather than retrying
                # forever, which would create an infinite zombie loop that
                # only a server restart can clear.
                if any(code in err_str for code in ("400", "401", "403")):
                    settings = getattr(self, "_settings", None)
                    model_name = getattr(settings, "model", "unknown") if settings else "unknown"
                    logger.error(
                        f"{self}: Deepgram rejected connection with a permanent HTTP error "
                        f"for model '{model_name}': {err_str}. "
                        f"Retry loop stopped. Update the assistant stt_model to a valid value "
                        f"(e.g. 'nova-3-general') and restart the call."
                    )
                    break
                # Transient error — wait before retrying to avoid a tight
                # loop when the connection fails too quickly to impose its
                # own natural backoff (e.g. DNS error, refused).
                logger.warning(f"{self}: Connection lost, will retry: {e}")
                await asyncio.sleep(0.5)
            finally:
                self._connection = None


class VoiceEngineFactory:
    """
    Factory for creating voice AI pipelines
    
    This encapsulates all Pipecat-specific code.
    Hotels never see this - they only interact with VoiceAgent.
    """
    
    @staticmethod
    def create_stt_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create STT service using Pipecat's proper configuration classes"""
        provider = config.stt_provider.lower()
        model = config.stt_model or "nova-3-general"
        
        if provider == "deepgram":
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

            # Validate the model against the canonical allowlist before
            # opening any Deepgram WebSocket.  This runs for ALL Deepgram
            # models — both standard and Flux — so an invalid model name
            # always fails immediately with a clear error rather than creating
            # an infinite retry loop (HTTP 400 → reconnect every ~250 ms).
            valid_models = _get_deepgram_valid_models()
            if model not in valid_models:
                raise ValueError(
                    f"Invalid Deepgram STT model '{model}'. "
                    f"Valid models: {sorted(valid_models)}. "
                    f"Update the assistant's stt_model field to a supported value."
                )

            # Check if using Flux model (advanced turn detection)
            if is_flux_model(model):
                return DeepgramFluxSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    settings=DeepgramFluxSTTService.Settings(
                        model=model,
                        eager_eot_threshold=config.stt_config.get("eager_eot_threshold"),
                        eot_threshold=config.stt_config.get("eot_threshold", 0.7),
                        eot_timeout_ms=config.stt_config.get("eot_timeout_ms", 5000),
                        keyterm=config.stt_config.get("keyterm", []),
                    ),
                )
            else:
                # Build a subclass that inherits BotelierDeepgramSTTService's
                # 4xx-abort logic as a defence-in-depth fallback.  Done inline
                # so DeepgramSTTService can be imported lazily.
                class _BotelierDeepgramSTTService(BotelierDeepgramSTTService, DeepgramSTTService):
                    pass

                # Standard Deepgram using the Settings API (pipecat 0.0.105+)
                return _BotelierDeepgramSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    settings=DeepgramSTTService.Settings(
                        model=model,
                        language=config.stt_language,
                        punctuate=config.stt_config.get("punctuate", True),
                        smart_format=config.stt_config.get("smart_format", True),
                        profanity_filter=config.stt_config.get("profanity_filter", True),
                        interim_results=True,
                        endpointing=config.stt_config.get("endpointing", 500),
                    ),
                )
        elif provider == "openai_whisper":
            from pipecat.services.openai.stt import OpenAISTTService
            return OpenAISTTService(
                api_key=api_keys.get("openai_api_key"),
                model=model or "whisper-1",
                language=config.stt_language,
            )
        elif provider == "assemblyai":
            from pipecat.services.assemblyai import AssemblyAISTTService
            return AssemblyAISTTService(
                api_key=api_keys.get("assemblyai_api_key"),
            )
        else:
            raise ValueError(f"Unsupported STT provider: {provider}")
    
    @staticmethod
    def create_llm_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create LLM service using Pipecat's proper InputParams classes"""
        provider = config.llm_provider.lower()
        
        if provider == "openai":
            from pipecat.services.openai.llm import OpenAILLMService
            from pipecat.services.openai.base_llm import BaseOpenAILLMService
            if hasattr(OpenAILLMService, "Settings"):
                return OpenAILLMService(
                    api_key=api_keys.get("openai_api_key"),
                    settings=OpenAILLMService.Settings(
                        model=config.llm_model,
                        temperature=config.llm_temperature,
                        max_completion_tokens=config.llm_max_tokens,
                        frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                        presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                        top_p=config.llm_config.get("top_p", 1.0),
                    ),
                )
            # Fallback for older Pipecat versions without Settings API
            params = BaseOpenAILLMService.InputParams(
                temperature=config.llm_temperature,
                max_completion_tokens=config.llm_max_tokens,
                frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                top_p=config.llm_config.get("top_p", 1.0),
            )
            return OpenAILLMService(
                api_key=api_keys.get("openai_api_key"),
                model=config.llm_model,
                params=params,
            )
        elif provider == "anthropic":
            # TODO: Anthropic support temporarily disabled due to SDK installation issues
            # Will be re-enabled once anthropic package is properly installed in Replit environment
            raise ValueError(
                "Anthropic LLM provider is temporarily unavailable. "
                "Please use OpenAI or Google Gemini instead."
            )
        elif provider == "google_gemini":
            from pipecat.services.google.llm import GoogleLLMService
            return GoogleLLMService(
                api_key=api_keys.get("google_api_key"),
                model=config.llm_model,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def create_tts_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create TTS service using Pipecat's configuration"""
        provider = config.tts_provider.lower()
        
        if provider == "deepgram":
            from pipecat.services.deepgram.tts import DeepgramTTSService
            voice = config.tts_voice_id or "aura-2-helena-en"
            # Twilio Media Streams require 8 kHz audio; tell Deepgram to encode at
            # 8000 Hz so no downstream resampling is needed before the Twilio
            # serialiser μ-law-encodes it for transmission.
            sample_rate = config.tts_config.get("sample_rate", 8000)
            encoding = config.tts_config.get("encoding", "linear16")
            if hasattr(DeepgramTTSService, "Settings"):
                return DeepgramTTSService(
                    api_key=api_keys.get("deepgram_api_key"),
                    sample_rate=sample_rate,
                    encoding=encoding,
                    settings=DeepgramTTSService.Settings(
                        voice=voice,
                    ),
                )
            return DeepgramTTSService(
                api_key=api_keys.get("deepgram_api_key"),
                voice=voice,
                sample_rate=sample_rate,
                encoding=encoding,
            )
        elif provider == "cartesia":
            from pipecat.services.cartesia.tts import CartesiaTTSService
            return CartesiaTTSService(
                api_key=api_keys.get("cartesia_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "elevenlabs":
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
            return ElevenLabsTTSService(
                api_key=api_keys.get("elevenlabs_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "openai":
            from pipecat.services.openai.tts import OpenAITTSService
            return OpenAITTSService(
                api_key=api_keys.get("openai_api_key"),
                voice=config.tts_voice_id or "alloy",
            )
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
    
    @staticmethod
    def create_pipeline(
        config: VoiceAgentConfig,
        api_keys: Dict[str, str],
        transport,
        function_schemas: Optional[list] = None,
        function_handlers: Optional[Dict[str, Any]] = None,
        on_interruption: Optional[Callable[[str], None]] = None,
        on_llm_response: Optional[Callable] = None,
        on_user_turn: Optional[Callable] = None,
        call_start_mono: float = 0.0,
        on_llm_start: Optional[Callable] = None,
    ) -> tuple:
        """
        Create complete voice pipeline from agent configuration.

        This is where Pipecat is actually used, but it's completely hidden
        from the hotel-facing API.

        Args:
            config: Voice agent configuration
            api_keys: API keys for external services
            transport: WebSocket transport
            function_schemas: Optional list of FunctionSchema objects for function calling
            function_handlers: Optional dict mapping function names to async handlers
            on_interruption: Optional callback called when user interrupts (receives interrupted text)
            on_llm_response: Optional callback(text, timestamp) called when each complete LLM
                response is assembled.  Used to recover responses from calls that drop mid-
                generation before the LLM context commits them.
            on_user_turn: Optional callback(text, timestamp) called for each finalized user
                utterance.  Used to record per-turn timestamps for the call transcript.

        Returns:
            11-tuple: (pipeline, task, llm, context_aggregator, context,
                      tts_completion_watcher, first_speech_tracker,
                      greeting_completion_tracker, idle_timeout_tracker,
                      user_turn_capture, tts_latency_tracker).
            - context is returned separately for transcript extraction.
            - tts_completion_watcher can be linked to FunctionMapper.set_tts_completion_watcher()
              so transfer handlers can await TTS completion without time-based sleeps.
            - first_speech_tracker / greeting_completion_tracker / idle_timeout_tracker /
              user_turn_capture / tts_latency_tracker need event_queue injected via
              set_event_queue() after pipeline creation.
        """
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        stt = VoiceEngineFactory.create_stt_service(config, api_keys)
        llm = VoiceEngineFactory.create_llm_service(config, api_keys)
        tts = VoiceEngineFactory.create_tts_service(config, api_keys)

        # Shared mutable timing state threaded through all latency-tracking processors.
        # Each processor writes a monotonic timestamp on its key event; downstream
        # processors read earlier timestamps to compute inter-stage deltas.
        #
        # Keys written per turn:
        #   "t_stt"       — UserTurnCapture on TranscriptionFrame
        #   "t_llm_start" — LLMResponseCapture on LLMFullResponseStartFrame
        #   "t_llm_end"   — LLMResponseCapture on LLMFullResponseEndFrame
        _timing_state: dict = {}

        llm_response_capture = LLMResponseCapture(
            on_llm_response=on_llm_response,
            on_llm_start=on_llm_start,
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        # Capture finalized user utterances for per-turn timestamp recording.
        # Placed after the STT mute filter so only post-muting transcriptions
        # (i.e. those that reach the LLM) are captured.  Pure observer.
        # call_start_mono enables per-turn STT latency logging.
        user_turn_capture = UserTurnCapture(
            on_user_turn=on_user_turn,
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        # Track text frames/interruptions before TTS
        interruption_tracker = InterruptionTracker(on_interruption=on_interruption)

        # Observe BotStoppedSpeakingFrame after TTS so transfer handlers can
        # await actual TTS completion rather than using fixed-duration sleeps.
        tts_completion_watcher = TtsCompletionWatcher()

        # Detect the caller's first speech utterance for event logging.
        # Placed between STT and context_aggregator so it intercepts
        # TranscriptionFrames before they enter the LLM pipeline.
        first_speech_tracker = FirstUserSpeechTracker()

        # Log greeting_completed on the first BotStoppedSpeakingFrame (greeting TTS done).
        # Placed between TTS and tts_completion_watcher; both see the same frame.
        greeting_completion_tracker = GreetingCompletionTracker()

        # Log idle_timeout when the caller goes silent for too long.
        # UserIdleProcessor fires a callback after `timeout` seconds of silence.
        idle_timeout_tracker = IdleTimeoutTracker(timeout=30.0)

        # Stamps t_last_inbound on every inbound AudioRawFrame from Twilio so that
        # UserTurnCapture can compute "Twilio inbound audio → STT finalized" delta.
        # Placed immediately after transport.input() — pure observer, zero latency impact.
        inbound_audio_tracker = InboundAudioTracker(timing_state=_timing_state)

        # Measures the final two pipeline-stage handoffs:
        #   3. LLM last token → TTS first audio chunk  (LLM→TTS delta, may be negative for streaming TTS)
        #   4. Dispatch of first audio chunk to transport.output() (call-relative timestamp)
        # Placed just before transport.output() so it sees AudioRawFrames on their way out
        # and also receives LLMFullResponseStartFrame flowing downstream from the LLM.
        tts_latency_tracker = TtsPipelineLatencyTracker(
            call_start_mono=call_start_mono,
            timing_state=_timing_state,
        )

        messages = [
            {
                "role": "system",
                "content": config.system_prompt,
            },
        ]

        # Create context with tools if schemas provided
        if function_schemas:
            tools = ToolsSchema(standard_tools=function_schemas)
            context = LLMContext(messages, tools=tools)
        else:
            context = LLMContext(messages)

        # Build LLMUserAggregatorParams integrating VAD, SmartTurn end-of-turn
        # detection, and mute strategies in one place.
        #
        # For the Silero VAD path this replaces the three deprecated Pipecat
        # APIs (TransportParams.vad_analyzer, TransportParams.turn_analyzer,
        # STTMuteFilter).  Combining them inside the aggregator eliminates the
        # race condition where a VAD speech-stop event fires while STT is muted,
        # leaving the first caller utterance orphaned with no end-of-turn signal.
        #
        # MuteUntilFirstBotCompleteUserMuteStrategy — suppresses user frames
        #   until the opening greeting finishes (replaces MUTE_UNTIL_FIRST_BOT_COMPLETE).
        # FunctionCallUserMuteStrategy — re-mutes during active tool/function
        #   calls (e.g. transfers) so the caller cannot interrupt mid-transfer
        #   (replaces FUNCTION_CALL).
        user_params: LLMUserAggregatorParams | None = None
        if config.enable_vad and config.vad_provider == "silero":
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
            vad_config = config.vad_config or {}
            vad_params = VADParams(
                confidence=vad_config.get("confidence", 0.7),
                start_secs=vad_config.get("start_secs", 0.2),
                stop_secs=vad_config.get("stop_secs", 0.8),
                min_volume=vad_config.get("min_volume", 0.6),
            )
            user_params = LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(params=vad_params),
                user_turn_strategies=UserTurnStrategies(
                    stop=[
                        TurnAnalyzerUserTurnStopStrategy(
                            turn_analyzer=LocalSmartTurnAnalyzerV3(
                                params=SmartTurnParams(
                                    stop_secs=vad_config.get("smart_turn_stop_secs", 1.0),
                                )
                            )
                        )
                    ]
                ),
                user_mute_strategies=[
                    MuteUntilFirstBotCompleteUserMuteStrategy(),
                    FunctionCallUserMuteStrategy(),
                ],
            )
            logger.info(f"Silero VAD + SmartTurn wired into LLMUserAggregator: {vad_params}")

        context_aggregator = LLMContextAggregatorPair(context, user_params=user_params)

        # Register function handlers with LLM
        if function_handlers:
            for function_name, handler in function_handlers.items():
                llm.register_function(function_name, handler)

        pipeline = Pipeline(
            [
                transport.input(),
                inbound_audio_tracker,         # Stamps t_last_inbound for Twilio→STT latency measurement
                stt,
                user_turn_capture,             # Records per-turn user timestamps for transcript (pure observer)
                first_speech_tracker,          # Detects caller's first utterance (non-blocking event log)
                idle_timeout_tracker.processor, # Logs idle_timeout when caller goes silent too long
                context_aggregator.user(),
                llm,
                llm_response_capture,          # Captures complete LLM responses for transcript recovery
                interruption_tracker,          # Observes text frames + InterruptionFrame before TTS
                tts,
                greeting_completion_tracker,   # Logs greeting_completed on first BotStoppedSpeakingFrame
                tts_completion_watcher,        # Observes BotStoppedSpeakingFrame after TTS
                tts_latency_tracker,           # Measures LLM→TTS and TTS→transport handoff latencies
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )

        return pipeline, task, llm, context_aggregator, context, tts_completion_watcher, first_speech_tracker, greeting_completion_tracker, idle_timeout_tracker, user_turn_capture, tts_latency_tracker
    
    @staticmethod
    def create_transport_params(config: VoiceAgentConfig):
        """Create transport parameters based on agent config"""
        from pipecat.transports.base_transport import TransportParams
        from pipecat.audio.vad.vad_analyzer import VADParams
        
        params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
        
        if config.enable_vad and config.vad_provider:
            vad_config = config.vad_config or {}
            
            try:
                if config.vad_provider == "silero":
                    # Silero VAD + SmartTurn are wired into LLMUserAggregatorParams
                    # inside create_pipeline() — nothing to set on TransportParams.
                    pass
                    
                elif config.vad_provider == "webrtc":
                    from pipecat.transports.daily.transport import WebRTCVADAnalyzer
                    
                    vad_params = VADParams(
                        confidence=vad_config.get("confidence", 0.5),
                        start_secs=vad_config.get("start_secs", 0.0),
                        stop_secs=vad_config.get("stop_secs", 0.2),
                        min_volume=vad_config.get("min_volume", 0.0)
                    )
                    params.vad_analyzer = WebRTCVADAnalyzer(params=vad_params)
                    logger.info(f"WebRTC VAD enabled with params: {vad_params}")
                    
                elif config.vad_provider == "aic":
                    from pipecat.audio.vad.aic_vad import AICVADAnalyzer
                    
                    lookback_buffer_size = vad_config.get("lookback_buffer_size")
                    sensitivity = vad_config.get("sensitivity")
                    params.vad_analyzer = AICVADAnalyzer(
                        lookback_buffer_size=lookback_buffer_size,
                        sensitivity=sensitivity
                    )
                    logger.info(f"AIC VAD enabled with lookback={lookback_buffer_size}, sensitivity={sensitivity}")
                    
                else:
                    logger.warning(f"Unknown VAD provider '{config.vad_provider}', VAD disabled")
                    
            except ImportError as e:
                logger.warning(f"VAD provider '{config.vad_provider}' not available (missing dependencies): {e}")
                logger.info("Continuing without VAD. Install dependencies or disable VAD in assistant settings.")
        
        return params
